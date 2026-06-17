"""
Lead escalator.

Marks a lead as escalated to human review (Tier 1 strategic handoff, exclusivity, or a
manual escalate action), records it, and flips the handoff trigger. Phase 3's
notifications / email layers hook onto the escalation activity; in Phase 2 the escalate
action is recorded and the lead flagged.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.leads.models import Lead, LeadActivity

logger = logging.getLogger("itrix")


def escalate_lead(lead: Lead, *, reason: str = "", by=None) -> Lead:
    """Escalate ``lead`` to human review, idempotently."""
    already = lead.escalated
    lead.escalated = True
    lead.human_handoff_trigger = True
    if not lead.escalated_at:
        lead.escalated_at = timezone.now()
    lead.save(update_fields=["escalated", "human_handoff_trigger", "escalated_at", "updated_at"])

    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.ESCALATED,
        label=reason or "Lead escalated to human review.",
        by=by,
        by_name=getattr(by, "display_name", "") or getattr(by, "email", "") or "system",
    )
    if not already:
        logger.info("Lead %s escalated (%s)", lead.id, reason or "manual")
    return lead
