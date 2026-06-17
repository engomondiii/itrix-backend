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


def create_evaluation_for_lead(lead) -> Evaluation:
    existing = Evaluation.objects.filter(
        lead=lead, status__in=[EvaluationStatus.PROPOSED, EvaluationStatus.IN_PROGRESS]
    ).first()
    if existing:
        return existing
    ev = Evaluation.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        pkg=select_package(lead.product_route),
        kpis=build_kpi_framework(lead.product_route),
    )
    logger.info("Evaluation created for lead %s (%s)", lead.id, ev.pkg)
    return ev
