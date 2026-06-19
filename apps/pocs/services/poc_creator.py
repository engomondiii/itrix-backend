"""
PoC creator.

Creates a proof-of-concept for a lead, seeding default milestones and KPIs (empty risks).
Idempotent per lead for an open PoC (planning/active). Moves the lead to the PoC status.
"""

from __future__ import annotations

import logging

from django.utils.dateparse import parse_date

from apps.pocs.models import PoC, PoCStatus
from apps.pocs.services.milestone_tracker import default_milestones
from apps.pocs.services.poc_kpi_recorder import default_kpis

logger = logging.getLogger("itrix")


def _coerce_extras(scope, duration_weeks, success_metrics, start_date) -> dict:
    """Normalise the optional PoC-setup fields the dashboard collects."""
    extras: dict = {}
    if scope is not None:
        extras["scope"] = str(scope)
    if duration_weeks is not None:
        try:
            extras["duration_weeks"] = int(duration_weeks)
        except (TypeError, ValueError):
            pass
    if success_metrics is not None:
        extras["success_metrics"] = str(success_metrics)
    if start_date is not None:
        parsed = start_date if hasattr(start_date, "year") else parse_date(str(start_date))
        if parsed:
            extras["start_date"] = parsed
    return extras


def create_poc_for_lead(
    lead, *, scope=None, duration_weeks=None, success_metrics=None, start_date=None
) -> PoC:
    """Create (or reuse) the lead's open PoC, capturing the optional
    scope/duration/success-metrics/start-date the dashboard collects."""
    extras = _coerce_extras(scope, duration_weeks, success_metrics, start_date)

    existing = PoC.objects.filter(
        lead=lead, status__in=[PoCStatus.PLANNING, PoCStatus.ACTIVE]
    ).first()
    if existing:
        if extras:
            for field, value in extras.items():
                setattr(existing, field, value)
            existing.save(update_fields=[*extras.keys(), "updated_at"])
        return existing
    poc = PoC.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        milestones=default_milestones(),
        kpis=default_kpis(),
        risks=[],
        **extras,
    )
    logger.info("PoC created for lead %s", lead.id)
    return poc
