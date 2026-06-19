"""
Evaluation creator.

Creates a paid evaluation for a lead, selecting the package from the lead's route and
seeding the KPI framework. Moves the lead to the Evaluation status. Idempotent per lead for
an open evaluation (proposed/in_progress).
"""

from __future__ import annotations

import logging

from apps.evaluations.models import Evaluation, EvaluationStatus
from apps.evaluations.services.kpi_framework_builder import build_kpi_framework
from apps.evaluations.services.package_selector import select_package

logger = logging.getLogger("itrix")


def create_evaluation_for_lead(
    lead, *, scope=None, fee=None, timeline=None
) -> Evaluation:
    """Create (or reuse) the lead's open evaluation, capturing the optional
    scope/fee/timeline the dashboard collects when the evaluation is requested."""
    extras = {}
    if scope is not None:
        extras["scope"] = str(scope)
    if fee is not None:
        extras["fee"] = str(fee)
    if timeline is not None:
        extras["timeline"] = str(timeline)

    existing = Evaluation.objects.filter(
        lead=lead, status__in=[EvaluationStatus.PROPOSED, EvaluationStatus.IN_PROGRESS]
    ).first()
    if existing:
        if extras:
            for field, value in extras.items():
                setattr(existing, field, value)
            existing.save(update_fields=[*extras.keys(), "updated_at"])
        return existing
    ev = Evaluation.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        pkg=select_package(lead.product_route),
        kpis=build_kpi_framework(lead.product_route),
        **extras,
    )
    logger.info("Evaluation created for lead %s (%s)", lead.id, ev.pkg)
    return ev
