"""Idempotent governed opening of a separate ALPHA Core opportunity."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.evaluations.models import Evaluation, EvaluationPackage, EvaluationStatus
from apps.leads.models import CommercialStage, LeadActivity
from apps.leads.services.commercial_progression import alpha_compute_gate, alpha_core_gate


@dataclass(frozen=True)
class AlphaCoreOpportunityResult:
    opportunity: Evaluation
    created: bool


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


@transaction.atomic
def open_alpha_core_opportunity(compute_evaluation: Evaluation, *, by=None) -> AlphaCoreOpportunityResult:
    """Open one ALPHA Core opportunity only after the existing evidence gate passes."""
    source = Evaluation.objects.select_for_update().select_related("lead").get(pk=compute_evaluation.pk)
    decision = alpha_core_gate(source)
    if not decision.allowed:
        raise ValueError("alpha_core_gate:" + ",".join(decision.reasons))

    compute_decision = alpha_compute_gate(
        source.lead,
        separate_workload=source.separate_workload,
        technical_route=source.technical_route,
    )
    if not compute_decision.allowed:
        raise ValueError("alpha_compute_gate:" + ",".join(compute_decision.reasons))

    # The separate Core opportunity is represented by the existing Evaluation domain.
    # One lead/account gets one open Core opportunity; retries return it unchanged.
    existing = Evaluation.objects.filter(
        lead=source.lead,
        pkg=EvaluationPackage.CORE,
        status__in=[EvaluationStatus.PROPOSED, EvaluationStatus.IN_PROGRESS],
    ).order_by("created_at").first()
    if existing is not None:
        return AlphaCoreOpportunityResult(existing, False)

    opportunity = Evaluation.objects.create(
        lead=source.lead,
        lead_name=source.lead_name,
        company=source.company,
        pkg=EvaluationPackage.CORE,
        status=EvaluationStatus.PROPOSED,
        scope=source.scope,
        hardware_value_case=source.hardware_value_case,
        hardware_target=source.hardware_target,
        hardware_economics=source.hardware_economics,
        hardware_sponsor=source.hardware_sponsor,
    )

    lead = source.lead
    lead.current_marketing_stage = CommercialStage.ALPHA_CORE
    progress = dict(lead.commercial_progress or {})
    progress.update(
        {
            "alpha_core_gate": True,
            "alpha_core_opportunity_id": str(opportunity.id),
            "alpha_core_source_assessment_id": str(source.id),
            "next_best_action": "alpha_core_opportunity",
        }
    )
    lead.commercial_progress = progress
    lead.save(update_fields=["current_marketing_stage", "commercial_progress", "updated_at"])

    LeadActivity.objects.create(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label="ALPHA Core opportunity opened from validated ALPHA Compute evidence.",
        by=by,
        by_name=_actor_name(by),
        meta={
            "domain": "alpha_core_opportunity",
            "opportunity_id": str(opportunity.id),
            "source_assessment_id": str(source.id),
        },
    )
    return AlphaCoreOpportunityResult(opportunity, True)
