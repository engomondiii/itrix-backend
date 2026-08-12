"""
THE SUPPORT QUEUE — row-level (Backend v7.1 Phase 2).

``analytics/support/`` answers "how deep is the queue and are we hitting SLA?". This
answers "whose problem am I working on next?" — and it is the endpoint that makes the
customer-first rule visible to an operator rather than merely enforced against them.

── WHY THIS IS LOAD-BEARING AND NOT A CONVENIENCE ──────────────────────────

§18.7: a blocking, unresolved support request makes a support action PRIMARY and
suppresses every commercial one. The backend enforces that in ``nba_precedence``. But an
operator who cannot SEE the blocking requests experiences the suppression as the system
being obstructive — "why won't it let me send the expansion note?" — and the predictable
response is to look for the override.

So the queue exists to make the rule legible. It orders BLOCKING FIRST, then by SLA
urgency, and it says on every row whether that request is currently suppressing expansion
for its customer. The operator sees the reason before they meet the consequence.

── AND NOTHING COMMERCIAL APPEARS ON A SUPPORT ROW ─────────────────────────
No licence-out probability, no lead score, no tier, no expansion candidate. A support
queue that carried them would invite an operator to open a customer's problem and leave
with a sales action — the precise inversion the rule exists to prevent. ``SupportCard`` on
Surface 1 was shipped with no action slot at all for the same reason; this is the team-plane
half of that decision.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger("itrix")

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# Worst first. Blocking outranks everything, then urgency, then how overdue it is.
_URGENCY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
_STATUS_RANK = {"open": 0, "in_progress": 1, "waiting_on_customer": 2, "resolved": 3}


def rows(
    *,
    limit: int = DEFAULT_LIMIT,
    include_resolved: bool = False,
    client_id: str | None = None,
    blocking_only: bool = False,
) -> list[dict]:
    """
    The queue as a work list. Blocking first, then urgency, then SLA breach.

    ``include_resolved`` defaults to False because a queue is what is outstanding. The
    resolved ones are still reachable — a resolved request whose customer said it did NOT
    actually fix their problem is exactly the row worth revisiting, and
    ``customer_confirmed_resolved`` is on every row for that reason.
    """
    from apps.customer_success.models import SupportRequest

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    now = timezone.now()

    qs = SupportRequest.objects.select_related("client", "owner")
    if not include_resolved:
        qs = qs.exclude(status=SupportRequest.Status.RESOLVED)
    if client_id:
        qs = qs.filter(client_id=client_id)
    if blocking_only:
        qs = qs.filter(blocking=True)

    out: list[dict] = []
    for req in qs[: limit * 2]:  # over-fetch a little; the sort below is authoritative
        client = req.client
        overdue_seconds = None
        if req.sla_due_at and req.status != SupportRequest.Status.RESOLVED:
            overdue_seconds = int((now - req.sla_due_at).total_seconds())

        out.append(
            {
                "requestId": str(req.id),
                "clientId": str(req.client_id),
                # `company`, consistently with every other row-level resource. Never an
                # inferred organisation — this is the Client's own recorded name.
                "company": getattr(client, "organization", "") or "",
                "subject": req.subject or "",
                "status": req.status,
                "urgency": req.urgency,
                # THE FIELD THE CUSTOMER-FIRST RULE READS.
                "blocking": bool(req.blocking),
                # Whether this row is currently suppressing expansion for its customer.
                # Stated per row so the operator meets the reason before the consequence.
                "suppressesExpansion": bool(req.blocking and req.is_open),
                "owner": req.owner_name or (getattr(req.owner, "email", "") or ""),
                "slaDueAt": req.sla_due_at.isoformat() if req.sla_due_at else None,
                "overdueSeconds": overdue_seconds,
                "slaBreaching": bool(overdue_seconds is not None and overdue_seconds > 0),
                "firstResponseAt": (
                    req.first_response_at.isoformat() if req.first_response_at else None
                ),
                "resolvedAt": req.resolved_at.isoformat() if req.resolved_at else None,
                # None means "not asked yet". False means the customer said it did NOT fix
                # their problem — which is the most important value on this row and the one
                # a naive boolean would have erased.
                "customerConfirmedResolved": req.customer_confirmed_resolved,
                "threadId": req.thread_id or None,
                "createdAt": req.created_at.isoformat(),
            }
        )

    out.sort(key=_sort_key)
    return out[:limit]


def _sort_key(row: dict) -> tuple:
    """
    Blocking first, then urgency, then most overdue, then oldest.

    Blocking is the FIRST key rather than a tiebreak on urgency, and that is deliberate:
    a "normal" urgency request that is blocking a customer outranks a "critical" one that
    is not, because blocking means the customer cannot proceed at all. Urgency is somebody's
    estimate; blocking is a fact about the customer's day.
    """
    return (
        0 if row["blocking"] else 1,
        _URGENCY_RANK.get(row["urgency"], 9),
        -(row["overdueSeconds"] or 0),
        _STATUS_RANK.get(row["status"], 9),
        row["createdAt"],
    )


def summary() -> dict:
    """
    The counts an operator needs above the queue.

    ``blockingOpen`` is the number that matters: while it is non-zero, expansion is
    suppressed for those customers and the operator should know why before they try.
    """
    from apps.customer_success.models import SupportRequest

    open_qs = SupportRequest.objects.exclude(status=SupportRequest.Status.RESOLVED)
    now = timezone.now()

    return {
        "open": open_qs.count(),
        "blockingOpen": open_qs.filter(blocking=True).count(),
        "breaching": open_qs.filter(sla_due_at__lt=now).count(),
        "unowned": open_qs.filter(owner__isnull=True, owner_name="").count(),
        # Resolved but the customer said otherwise. Not a queue item by status, and very
        # much a queue item in practice.
        "resolvedButNotConfirmed": SupportRequest.objects.filter(
            status=SupportRequest.Status.RESOLVED, customer_confirmed_resolved=False
        ).count(),
    }


def detail(request_id: str) -> dict | None:
    """
    One request, with its body and its resolution note.

    The body is the CUSTOMER'S OWN WORDS. It is not summarised, not truncated and not
    re-worded — an operator working a problem needs what was actually said, and a summary
    is where the detail that mattered gets lost.
    """
    from apps.customer_success.models import SupportRequest

    req = (
        SupportRequest.objects.select_related("client", "owner")
        .filter(id=request_id)
        .first()
    )
    if req is None:
        return None

    base = rows(limit=1, include_resolved=True, client_id=str(req.client_id))
    row = next((r for r in base if r["requestId"] == str(req.id)), None) or {}

    return {
        **row,
        "requestId": str(req.id),
        "body": req.body or "",
        "resolutionNote": req.resolution_note or "",
    }


# ═════════════════════════════════════════════════════════════════════════════
# ACTIONS (2026-08-12) — the queue becomes a work list you can work
# ═════════════════════════════════════════════════════════════════════════════
# The queue was read-only: an operator could see whose problem was blocking them and
# had no way to take it or close it from here, so the row that explained the
# suppression could not be the row that ended it. Two actions, no more:
#
#   assign()   take it, hand it over, or drop it
#   resolve()  close it, WITH a note
#
# ── WHAT THESE DELIBERATELY DO NOT DO ───────────────────────────────────────
# They do not touch `blocking`, `urgency` or `customer_confirmed_resolved`.
#   * `blocking` is the customer's situation, not an operator's opinion, and it is the
#     field NBA suppression reads — an operator who could clear it could unblock their
#     own expansion action by relabelling somebody else's problem.
#   * `customer_confirmed_resolved` is the CUSTOMER'S answer. Resolving sets
#     `resolved_at`; whether it actually helped is theirs to say, and it stays None
#     ("not asked yet") until they do.


class SupportActionRefused(Exception):
    """Raised when an action cannot apply. Carries a machine reason and a sentence."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def assign(request_id: str, *, owner, by=None) -> dict | None:
    """
    Set (or clear) the owner of one support request.

    ``owner`` None clears it — a request nobody is holding is an honest state and the
    queue shows it, which is better than an operator staying nominally responsible for
    something they have handed on.

    Unlike lead assignment this is NOT assign-if-unowned. A support request is not a
    commercial claim; passing one to whoever is on shift is a normal, expected handover,
    and requiring a force flag would train people to always send it.
    """
    from apps.customer_success.models import SupportRequest

    req = SupportRequest.objects.select_related("client", "owner").filter(id=request_id).first()
    if req is None:
        return None

    req.owner = owner
    req.owner_name = _display(owner)
    fields = ["owner", "owner_name", "updated_at"]

    # Taking an open request is the first response to it, if nobody has responded yet.
    # Recorded here because the SLA clock is measured against it and an operator should
    # not have to remember to stamp it.
    if owner is not None and req.first_response_at is None and req.is_open:
        req.first_response_at = timezone.now()
        fields.append("first_response_at")

    req.save(update_fields=fields)
    logger.info(
        "cockpit.support.assigned request=%s owner=%s by=%s",
        req.id, getattr(owner, "id", None), getattr(by, "id", None),
    )
    return detail(str(req.id))


def resolve(request_id: str, *, note: str, by=None) -> dict | None:
    """
    Close one support request, with the note that says what was done.

    ── THE NOTE IS REQUIRED, AND IT IS REQUIRED HERE ────────────────────────────
    Not in the UI. A resolution with no note is a row that says a customer's problem
    ended and cannot say how, and the next person to meet the same problem starts from
    nothing. Enforcing it in the service means the rule holds for a direct API call as
    well as for the button — the same reason the attachment release reason is enforced
    at this layer.

    Idempotent: resolving an already-resolved request keeps the FIRST `resolved_at` and
    does not overwrite the original note. The first close is when it stopped blocking
    the customer, and that timestamp is what the health calculation reads.
    """
    from apps.customer_success.models import SupportRequest

    body = (note or "").strip()
    if not body:
        raise SupportActionRefused(
            "note_required",
            "Add a short note saying how this was resolved before closing it.",
        )

    req = SupportRequest.objects.select_related("client", "owner").filter(id=request_id).first()
    if req is None:
        return None

    if req.status == SupportRequest.Status.RESOLVED:
        return detail(str(req.id))

    req.status = SupportRequest.Status.RESOLVED
    req.resolved_at = timezone.now()
    req.resolution_note = body
    fields = ["status", "resolved_at", "resolution_note", "updated_at"]
    if req.first_response_at is None:
        req.first_response_at = req.resolved_at
        fields.append("first_response_at")
    req.save(update_fields=fields)

    logger.info(
        "cockpit.support.resolved request=%s blocking=%s by=%s",
        req.id, req.blocking, getattr(by, "id", None),
    )
    return detail(str(req.id))


def _display(user) -> str:
    if user is None:
        return ""
    return (
        getattr(user, "display_name", "")
        or getattr(user, "name", "")
        or getattr(user, "email", "")
        or ""
    )
