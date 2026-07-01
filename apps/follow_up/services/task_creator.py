"""
Follow-up task creator.

Creates the SLA follow-up task for a lead (used by the lead-creation fan-out). Idempotent
per lead: a lead gets at most one open follow-up task. Tier 4 leads (no SLA) get no task.
"""

from __future__ import annotations

import logging

from apps.follow_up.models import FollowUpStatus, FollowUpTask
from apps.follow_up.services.sla_calculator import due_at_for_tier

logger = logging.getLogger("itrix")


def create_followup_for_lead(lead) -> FollowUpTask | None:
    """Create (or return existing) the follow-up task for a lead."""
    due = due_at_for_tier(lead.tier, start=lead.submitted_at)
    if due is None:
        logger.info("Lead %s is Tier %s — no follow-up SLA task.", lead.id, lead.tier)
        return None

    existing = FollowUpTask.objects.filter(
        lead=lead, status__in=[FollowUpStatus.PENDING, FollowUpStatus.SNOOZED]
    ).first()
    if existing:
        return existing

    task = FollowUpTask.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        tier=lead.tier,
        owner=lead.owner,
        due_at=due,
    )
    logger.info("Follow-up task created for lead %s (due %s)", lead.id, due)
    return task


def create_journey_task(lead, *, to_state: str) -> "FollowUpTask | None":
    """
    Create/refresh a follow-up task when the journey reaches a state that warrants team
    action (INVITED / CLIENT / ENGAGED). DIAGNOSED already gets an SLA task at lead
    creation, so it is skipped here. Idempotent per lead (reuses the open task).
    """
    if to_state not in {"INVITED", "CLIENT", "ENGAGED"}:
        return None
    existing = FollowUpTask.objects.filter(
        lead=lead, status__in=[FollowUpStatus.PENDING, FollowUpStatus.SNOOZED]
    ).first()
    if existing:
        return existing
    from apps.follow_up.services.sla_calculator import due_at_for_tier

    due = due_at_for_tier(lead.tier, start=lead.updated_at)
    if due is None:
        return None
    return FollowUpTask.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        tier=lead.tier,
        owner=lead.owner,
        due_at=due,
    )
