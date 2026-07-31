"""
The conversation -> client-page bridge (states 3 -> 4).

── WHAT WAS MISSING ─────────────────────────────────────────────────────────
The conversational surface takes an anonymous visitor through the qualification
band (ARRIVED -> IN_REVIEW -> DIAGNOSED) but STOPPED at DIAGNOSED. The custom
"pitch room" the visitor is meant to receive is State 4 (CLIENT_PAGE), reached by
the ``reveal_client_page`` transition, which mints the ``/c/<token>`` capability
token. That transition, plus the Lead it needs, only ever existed in the OLD
structured-form path (``review.qualification_processor``) — which scores Q1-Q9
answers and creates a Lead. The conversation produces neither, so it never crossed
3 -> 4 and the visitor never got a page.

This bridge closes that gap WITHOUT duplicating the reveal machinery. When the
conversation has (a) reached DIAGNOSED and (b) captured the visitor's company and
a valid email, it:

    1. creates a real Lead from the thread (lead_source=conversation, honest
       exploratory defaults — no fabricated Q1-Q9 score),
    2. attaches the captured contact via the existing email-capture path,
    3. claims the anonymous thread onto that Lead so the conversation continues
       as the same thread,
    4. fires the EXISTING ``reveal_client_page`` transition (3 -> 4), which mints
       the client-page token exactly as the form path does,
    5. broadcasts the reveal to the THREAD's socket group (the anonymous visitor
       is subscribed there, not to a lead group) and returns the ``/c/<token>``
       URL so the reply can include a link.

Everything here is best-effort and idempotent: a thread that already has a lead /
already revealed is a satisfied no-op, and any failure leaves the conversation
working (the visitor still has their transcript; they simply have not been handed
a page yet).

── WHY THE TRIGGER IS "DIAGNOSED + CONTACT" ─────────────────────────────────
The page is the delivered value. Revealing it before DIAGNOSED would hand it over
before the review has actually happened; requiring contact means the visitor has
shown intent and we have somewhere to anchor the Lead. This matches the form
path, where the client page is revealed only after qualification completes.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("itrix")

# A company line the visitor typically gives alongside the email. Deliberately
# permissive: we would rather capture a slightly-off company string than miss a
# real one, and the operator sees and can correct it in the cockpit.
_COMPANY_PATTERNS = (
    re.compile(r"(?:company|org(?:ani[sz]ation)?|employer|firm|startup|team)\s*(?:is|:|=|named|called)?\s*([A-Z0-9][\w&.\- ]{1,60})", re.IGNORECASE),
    re.compile(r"(?:i(?:'m| am)\s+(?:from|with|at)|we(?:'re| are)\s+(?:from|at))\s+([A-Z0-9][\w&.\- ]{1,60})", re.IGNORECASE),
)
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_contact(text: str) -> dict:
    """
    Pull a company and email from one visitor turn.

    Returns ``{"email": str, "company": str}`` with empty strings for anything not
    found. The email is validated + normalised with the same validator the rest of
    the system uses, so a malformed address is treated as absent rather than stored.
    """
    result = {"email": "", "company": ""}
    if not (text or "").strip():
        return result

    m = _EMAIL_PATTERN.search(text)
    if m:
        try:
            from apps.core.validators import validate_email_address

            result["email"] = validate_email_address(m.group(0))
        except Exception:  # noqa: BLE001 - an invalid address is simply not captured
            result["email"] = ""

    for pattern in _COMPANY_PATTERNS:
        cm = pattern.search(text)
        if cm:
            company = cm.group(1).strip().strip(".,;")
            # Trim a trailing "and ... email ..." clause the first pattern can over-capture.
            company = re.split(r"\s+and\s+|\s+contact\s+|\s+email\s+|\s+my\s+", company, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if company and "@" not in company:
                result["company"] = company[:200]
                break

    return result


def maybe_reveal_client_page(thread, body: str) -> dict:
    """
    If the conversation is ready, create the Lead and reveal the client page.

    Returns a dict describing what happened:
        {"revealed": bool, "token": str|None, "url": str|None, "reason": str}

    ``revealed`` is True only when this call performed the 3 -> 4 reveal. It is a
    no-op (revealed=False) when the loop has not closed, contact is missing, the
    thread already has a lead, or the feature is unavailable.
    """
    out = {"revealed": False, "token": None, "url": None, "reason": ""}
    if thread is None:
        out["reason"] = "no_thread"
        return out

    # Already bound to a subject? Then the reveal (if any) already happened through
    # the normal lead path; nothing for the bridge to do.
    if getattr(thread, "lead_id", None):
        out["reason"] = "already_has_lead"
        return out

    from apps.conversations.services import thread_state

    # Gate 1: the qualification loop must have closed (value delivered).
    if thread_state.current_state_number(thread) < 3:
        out["reason"] = "not_diagnosed"
        return out

    # Gate 2: we need a company AND a valid email to anchor the Lead and the page.
    contact = extract_contact(body)
    if not (contact["email"] and contact["company"]):
        out["reason"] = "contact_incomplete"
        return out

    try:
        lead = _create_conversation_lead(thread, contact)
    except Exception:  # noqa: BLE001 - never break the turn on lead creation
        logger.exception("conversation lead creation failed for thread %s", getattr(thread, "id", "?"))
        out["reason"] = "lead_create_failed"
        return out

    # Fire the EXISTING reveal transition (3 -> 4). This mints the client-page token.
    try:
        from apps.journey.services.advance import reveal_client_page

        result = reveal_client_page(lead, meta={"source": "conversation", "thread_id": str(thread.id)})
        reveal = getattr(result, "reveal", None) or {}
        token = reveal.get("capability_token") if isinstance(reveal, dict) else None
    except Exception:  # noqa: BLE001
        logger.exception("reveal_client_page failed for lead %s", getattr(lead, "id", "?"))
        out["reason"] = "reveal_failed"
        return out

    # Mirror the thread's state so the shell reports CLIENT_PAGE.
    try:
        thread_state._mirror_onto_thread(thread, "CLIENT_PAGE")
    except Exception:  # noqa: BLE001
        pass

    url = _client_page_url(token) if token else None
    _broadcast_reveal_to_thread(thread, reveal if isinstance(reveal, dict) else {}, token)

    out.update({"revealed": True, "token": token, "url": url, "reason": "revealed"})
    logger.info("client page revealed from conversation for thread %s (lead %s)", thread.id, lead.id)
    return out


def _create_conversation_lead(thread, contact: dict):
    """
    Create a real Lead from an anonymous thread and claim the thread onto it.

    Uses honest exploratory defaults (general route, tier 4) rather than inventing a
    Q1-Q9 score the conversation never produced. The Lead is marked
    ``lead_source=conversation`` — the model's own default and exactly the case it
    describes ("somebody described a problem and Layer 1 qualified them").
    """
    from django.db import transaction

    from apps.leads.models import Lead, LeadActivity, LeadSource
    from apps.review.models import ReviewSession

    first_turn = _first_visitor_turn(thread)

    with transaction.atomic():
        # A minimal ReviewSession gives the existing reveal/token code the shape it
        # expects (it reads lead.review_session for the prompt), without pretending a
        # structured qualification happened.
        session = ReviewSession.objects.create(
            client_id="",
            visitor_type="conversation",
            status=ReviewSession.Status.QUALIFIED,
            prompt=first_turn[:2000],
        )

        lead = Lead.objects.create(
            review_session=session,
            lead_source=LeadSource.CONVERSATION,
            visitor_name="",
            company=contact["company"],
            email=contact["email"],
            product_route="general",
            tier=4,
            score=0,
            journey_state="DIAGNOSED",
            compute_bottleneck=first_turn[:500],
            recommended_next_step="Client page revealed from conversation.",
        )

        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.SUBMISSION,
            label="Lead created from conversation — contact captured, client page revealed.",
            meta={"source": "conversation", "thread_id": str(thread.id), "company": contact["company"]},
        )

        # Claim the anonymous thread onto this lead so the conversation continues as
        # the same thread and its turns/artifacts are preserved.
        _attach_thread_to_lead(thread, lead)

    return lead


def _attach_thread_to_lead(thread, lead) -> None:
    """Bind the thread (and its conversation) to the new lead, preserving history."""
    thread.lead = lead
    fields = ["lead", "updated_at"]
    # A thread that was anonymous keeps its owner_kind (still a visitor session), but
    # now points at a lead so shell.for_subject drives it.
    thread.save(update_fields=fields)

    conversation = getattr(thread, "conversation", None)
    if conversation is not None and getattr(conversation, "lead_id", None) != lead.id:
        try:
            conversation.lead = lead
            conversation.save(update_fields=["lead", "updated_at"])
        except Exception:  # noqa: BLE001
            logger.debug("could not attach conversation to lead for thread %s", getattr(thread, "id", "?"))


def _broadcast_reveal_to_thread(thread, reveal: dict, token) -> None:
    """
    Push ``journey.reveal`` + a shell update to the THREAD's socket group.

    The anonymous visitor's socket is subscribed to the thread group, not to a lead
    group, so the reveal that ``advance`` emitted to the lead group would not reach
    them. We re-emit to the thread group here so an open transcript navigates live.
    Best-effort: if realtime is unavailable the visitor still gets the link in the
    reply (see the caller).
    """
    try:
        from apps.conversations.services.fan_out import (
            broadcast_reveal,
            broadcast_shell_update,
        )
        from apps.journey.services import shell

        payload = {
            "state": reveal.get("state", "CLIENT_PAGE"),
            "surface": reveal.get("surface", "client_page"),
            "capability_token": token,
            "value_delivered": True,
        }
        broadcast_reveal(thread.group_name, payload)

        contract = (
            shell.for_subject(thread.lead, thread=thread)
            if getattr(thread, "lead_id", None)
            else shell.for_anonymous_thread(thread)
        )
        broadcast_shell_update(thread.group_name, contract)
    except Exception:  # noqa: BLE001 - realtime must never break the turn
        logger.debug("reveal fan-out to thread group failed for thread %s", getattr(thread, "id", "?"))


def _client_page_url(token: str) -> str:
    """Build the visitor-facing /c/<token> URL from the configured web origin."""
    from django.conf import settings

    base = (
        getattr(settings, "FRONTEND_WEB_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or ""
    ).rstrip("/")
    path = f"/c/{token}"
    return f"{base}{path}" if base else path


def _first_visitor_turn(thread) -> str:
    from apps.conversations.models import Message

    m = (
        Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
        .order_by("seq", "created_at")
        .first()
    )
    return (m.body or "") if m else ""
