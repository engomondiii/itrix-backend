"""
PoC creator.

Creates a proof-of-concept for a lead, seeding default milestones and KPIs (empty risks).
Idempotent per lead for an open PoC (planning/active). Moves the lead to the PoC status.
"""

from __future__ import annotations

import logging

from apps.pocs.models import PoC, PoCStatus
from apps.pocs.services.milestone_tracker import default_milestones
from apps.pocs.services.poc_kpi_recorder import default_kpis

logger = logging.getLogger("itrix")


def create_poc_for_lead(lead) -> PoC:
    existing = PoC.objects.filter(
        lead=lead, status__in=[PoCStatus.PLANNING, PoCStatus.ACTIVE]
    ).first()
    if existing:
        return existing
    poc = PoC.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        milestones=default_milestones(),
        kpis=default_kpis(),
        risks=[],
    )
    logger.info("PoC created for lead %s", lead.id)
    return poc
