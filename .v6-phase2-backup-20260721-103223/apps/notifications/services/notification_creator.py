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
