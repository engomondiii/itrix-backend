"""
Support routing (Backend v6.0 §Phase 2, Playbook §12D).

    detect_support_intent(text)  -> bool
    route(client, body, thread)  -> SupportRequest

── THE RULE THAT MATTERS MOST IN THIS MODULE ────────────────────────────────
NEVER SELL INTO A SUPPORT THREAD.

    A support reply helps with the problem and stops. It does not mention another
    workload, an expansion, a renewal, or a next agreement — no matter how natural the
    segue seems.

That is enforced in two places: the claim checker refuses a commercial claim in a support
context, and this module marks the request so the NBA engine suppresses commercial
actions while it is open. Neither relies on the agent choosing well.

── WHY INTENT DETECTION IS DETERMINISTIC ────────────────────────────────────
Layer 1 stays LLM-free. If a model decided what counted as a support request, then a
model would be deciding when the commercial suppression rule applies — which is exactly
the kind of judgement the architecture keeps outside the model.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("itrix")

# Phrases that mean "something is wrong". Deliberately broad: a false positive routes a
# question to a human, which is a good failure. A false negative answers a broken
# deployment with a sales reply, which is the failure this exists to prevent.
_SUPPORT_SIGNALS = (
    r"\bnot working\b", r"\bbroken\b", r"\bbreaks?\b", r"\bfail(?:ed|ing|s)?\b",
    r"\berror\b", r"\bcrash(?:ed|ing|es)?\b", r"\bdown\b", r"\boutage\b",
    r"\bstuck\b", r"\bhang(?:ing|s)?\b", r"\btimeout\b", r"\bcannot\b", r"\bcan't\b",
    r"\bunable to\b", r"\bregression\b", r"\bbug\b", r"\bissue\b", r"\bproblem\b",
    r"\bhelp\b", r"\bsupport\b", r"\burgent\b", r"\bblocked\b", r"\bblocking\b",
    r"\bwrong (?:result|output|answer)\b", r"\bdoes not (?:work|run|start)\b",
)
_SUPPORT_RE = re.compile("|".join(_SUPPORT_SIGNALS), re.IGNORECASE)

# Signals that the customer cannot proceed at all.
_BLOCKING_SIGNALS = (
    r"\bblocked\b", r"\bblocking\b", r"\bdown\b", r"\boutage\b", r"\bproduction\b",
    r"\burgent\b", r"\bcritical\b", r"\bcannot (?:run|deploy|proceed|continue)\b",
    r"\bstopped\b", r"\bcompletely\b",
)
_BLOCKING_RE = re.compile("|".join(_BLOCKING_SIGNALS), re.IGNORECASE)

_URGENCY_CRITICAL = (r"\bproduction\b", r"\boutage\b", r"\bcritical\b", r"\bdata loss\b")
_URGENCY_HIGH = (r"\burgent\b", r"\basap\b", r"\bblocked\b", r"\bblocking\b")

_CRITICAL_RE = re.compile("|".join(_URGENCY_CRITICAL), re.IGNORECASE)
_HIGH_RE = re.compile("|".join(_URGENCY_HIGH), re.IGNORECASE)


def detect_support_intent(text: str) -> bool:
    """True when this turn is asking for help rather than asking a question."""
    return bool(text and _SUPPORT_RE.search(text))


def detect_blocking(text: str) -> bool:
    """True when the customer appears unable to proceed."""
    return bool(text and _BLOCKING_RE.search(text))


def detect_urgency(text: str) -> str:
    from apps.customer_success.models import SupportRequest

    if text and _CRITICAL_RE.search(text):
        return SupportRequest.Urgency.CRITICAL
    if text and _HIGH_RE.search(text):
        return SupportRequest.Urgency.HIGH
    return SupportRequest.Urgency.NORMAL


def sla_hours() -> int:
    return int(getattr(settings, "SUPPORT_SLA_DEFAULT_HOURS", 4))


def route(client, body: str, *, thread=None, subject: str = "") -> "object":
    """
    Create a SupportRequest from a customer turn and assign an owner.

    Called by ingest when support intent is detected on a State 10 thread. Returns the
    created request so the caller can acknowledge it with the owner's name and the SLA —
    the acknowledgement in the Playbook is "We have this. {owner} owns it and will
    respond within {sla}", which is only possible if both are resolved at creation time.
    """
    from apps.customer_success.models import RelationshipTeamMember, SupportRequest

    urgency = detect_urgency(body)
    blocking = detect_blocking(body)

    # Critical always counts as blocking regardless of phrasing.
    if urgency == SupportRequest.Urgency.CRITICAL:
        blocking = True

    owner_member = (
        RelationshipTeamMember.objects.filter(
            client=client, role=RelationshipTeamMember.Role.SUPPORT
        ).first()
        or RelationshipTeamMember.objects.filter(
            client=client, role=RelationshipTeamMember.Role.CUSTOMER_SUCCESS
        ).first()
    )

    request = SupportRequest.objects.create(
        client=client,
        thread_id=str(getattr(thread, "id", "") or ""),
        subject=(subject or _derive_subject(body))[:300],
        body=body or "",
        urgency=urgency,
        blocking=blocking,
        owner=getattr(owner_member, "user", None),
        owner_name=getattr(owner_member, "display_name", "") or "itriX Support",
        sla_due_at=timezone.now() + timezone.timedelta(hours=sla_hours()),
    )

    logger.info(
        "support.route client=%s urgency=%s blocking=%s request=%s",
        getattr(client, "id", "?"),
        urgency,
        blocking,
        request.id,
    )
    _notify(request)
    return request


def _derive_subject(body: str) -> str:
    text = " ".join((body or "").split())
    if not text:
        return "Support request"
    first = re.split(r"(?<=[.!?])\s", text)[0]
    return first[:120] + ("..." if len(first) > 120 else "")


def _notify(request) -> None:
    """Best-effort team notification. A notification failure never loses the request."""
    try:
        from apps.notifications.services.notification_creator import notify_support_request

        notify_support_request(request)
    except Exception:  # noqa: BLE001
        logger.debug("support notification skipped (notifier unavailable)")


def acknowledge_copy(request) -> str:
    """
    The exact acknowledgement wording (Playbook §12D).

    Kept here rather than in a template so the owner and SLA are always the REAL ones.
    An acknowledgement that promises a response time nobody is tracking is worse than
    none at all.
    """
    owner = request.owner_name or "Your support owner"
    hours = sla_hours()
    return f"We have this. {owner} owns it and will respond within {hours} hours."


def open_blocking_for(client) -> bool:
    """Whether a blocking, unresolved request exists. Read by the NBA rule."""
    from apps.customer_success.models import SupportRequest

    if client is None:
        return False
    return SupportRequest.objects.filter(
        client=client, blocking=True, resolved_at__isnull=True
    ).exists()


def resolve(request, *, note: str = "", actor=None):
    """Resolve a request and ask the one question that matters afterwards."""
    from apps.customer_success.models import SupportRequest

    request.status = SupportRequest.Status.RESOLVED
    request.resolved_at = timezone.now()
    request.resolution_note = note or request.resolution_note
    request.save(update_fields=["status", "resolved_at", "resolution_note", "updated_at"])

    # "Did this actually resolve it for you?" — the customer decides, not us.
    try:
        from apps.customer_success.services.health_calculator import recompute

        recompute(request.client)
    except Exception:  # noqa: BLE001
        pass
    return request


POST_RESOLUTION_PROMPT = "Did this actually resolve it for you?"
