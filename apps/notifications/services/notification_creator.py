"""
Notification creator.

Helper functions to create notifications, including the lead-driven ones used by the
lead-creation fan-out (new lead, Tier-1 lead, escalation, SLA breach, NDA signed). Keeping
creation here means callers don't repeat title/body/href wiring.
"""

from __future__ import annotations

import logging

from apps.notifications.models import Notification

logger = logging.getLogger("itrix")


def create_notification(*, kind: str, title: str, body: str = "", href: str = "", lead=None) -> Notification:
    return Notification.objects.create(
        kind=kind, title=title, body=body, href=href, lead=lead
    )


def notify_new_lead(lead) -> Notification:
    who = lead.company or lead.visitor_name or "A visitor"
    href = f"/leads/{lead.id}"
    if lead.tier == 1:
        return create_notification(
            kind=Notification.Kind.TIER1_LEAD,
            title=f"Tier 1 lead: {who}",
            body=f"Score {lead.score} · {lead.product_route_display} · respond within 24h.",
            href=href,
            lead=lead,
        )
    return create_notification(
        kind=Notification.Kind.NEW_LEAD,
        title=f"New lead: {who}",
        body=f"Score {lead.score} · Tier {lead.tier} · {lead.product_route_display}.",
        href=href,
        lead=lead,
    )


def notify_escalation(lead, *, reason: str = "") -> Notification:
    who = lead.company or lead.visitor_name or "A lead"
    return create_notification(
        kind=Notification.Kind.ESCALATION,
        title=f"Escalation: {who}",
        body=reason or "Lead escalated to human review.",
        href=f"/leads/{lead.id}",
        lead=lead,
    )


def notify_sla_breach(task) -> Notification:
    return create_notification(
        kind=Notification.Kind.SLA_BREACH,
        title=f"SLA breached: {task.lead_name}",
        body=f"Tier {task.tier} follow-up is overdue.",
        href=f"/leads/{task.lead_id}",
        lead=getattr(task, "lead", None),
    )


def notify_nda_signed(nda) -> Notification:
    return create_notification(
        kind=Notification.Kind.NDA_SIGNED,
        title=f"NDA signed: {nda.lead_name}",
        body="NDA is signed — detailed disclosure is now permitted.",
        href=f"/leads/{nda.lead_id}",
        lead=getattr(nda, "lead", None),
    )


def notify_journey_event(lead, *, to_state: str) -> "Notification | None":
    """
    Create a team notification when a lead's journey reaches a key state
    (DIAGNOSED / INVITED / CLIENT / ENGAGED). Best-effort; unknown states are ignored.
    Uses the SYSTEM kind so no schema change is required.
    """
    who = lead.company or lead.visitor_name or lead.email or "A lead"
    titles = {
        "DIAGNOSED": f"Diagnosed: {who}",
        "INVITED": f"Invited to workspace: {who}",
        "CLIENT": f"New client account: {who}",
        "ENGAGED": f"Engaged (NDA/eval): {who}",
    }
    title = titles.get(to_state)
    if not title:
        return None
    return create_notification(
        kind=Notification.Kind.SYSTEM,
        title=title,
        body=f"Journey advanced to {to_state}.",
        href=f"/leads/{lead.id}",
        lead=lead,
    )


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 2 notification hooks
# ─────────────────────────────────────────────────────────────────────────────
# Every one is best-effort at the call site. A notification failure must never affect
# the thing it was reporting on — a quarantined file is still quarantined whether or not
# anyone was told promptly.
import logging as _logging

_logger = _logging.getLogger("itrix")


def notify_support_request(request) -> None:
    """A new support request. Blocking ones are the ones that page."""
    _logger.info(
        "notify.support_request client=%s urgency=%s blocking=%s subject=%r",
        getattr(request, "client_id", "?"), request.urgency, request.blocking,
        (request.subject or "")[:80],
    )


def notify_sla_breach(request) -> None:
    """
    A support request passed its SLA with no first response.

    Worse than an unacknowledged request, because the customer was TOLD a time.
    """
    _logger.warning(
        "notify.sla_breach request=%s client=%s due=%s",
        getattr(request, "id", "?"), getattr(request, "client_id", "?"),
        getattr(request, "sla_due_at", None),
    )


def notify_feedback_risk(pulse) -> None:
    """
    A negative pulse or an explicit follow-up request.

    Goes to the NAMED SUCCESS OWNER and nowhere else — the score never travels further.
    """
    _logger.info(
        "notify.feedback_risk client=%s follow_up=%s",
        getattr(pulse, "client_id", "?"), getattr(pulse, "wants_follow_up", False),
    )


def notify_success_review_due(review) -> None:
    _logger.info(
        "notify.success_review_due client=%s at=%s",
        getattr(review, "client_id", "?"), getattr(review, "scheduled_at", None),
    )


def notify_attachment_quarantine(attachment, scan) -> None:
    """A file was quarantined. The team sees it; the visitor sees only the honest note."""
    _logger.warning(
        "notify.attachment_quarantine attachment=%s verdict=%s thread=%s",
        getattr(attachment, "id", "?"), getattr(scan, "verdict", "?"),
        getattr(attachment, "thread_id", "?"),
    )


def notify_stream_guard_halt(hit) -> None:
    """
    A rising guard-hit rate is RETRIEVAL OR PROMPT DRIFT, not noise (§6.4).
    """
    _logger.warning(
        "notify.stream_guard_halt category=%s pattern=%s",
        getattr(hit, "category", "?"), getattr(hit, "pattern", "?"),
    )
