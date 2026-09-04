"""Canonical cross-product commercial progression state.

The existing Lead/ASTOPEngagement/Evaluation records remain authoritative. This service
only derives and synchronizes the denormalized gate flags and next action already stored
in ``Lead.commercial_progress``; it does not create another product-state model.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from django.db import transaction

from apps.evaluations.models import Evaluation, EvaluationPackage, EvaluationStatus
from apps.leads.models import ASTOPEngagement, ASTOPStage, CommercialStage, Lead, LeadActivity
from apps.leads.services.commercial_progression import (
    alpha_compute_gate,
    alpha_core_gate,
    controlled_evaluation_proof_gate,
)

_NON_TERMINAL_PRODUCT_STATUSES = {
    EvaluationStatus.PROPOSED,
    EvaluationStatus.IN_PROGRESS,
    EvaluationStatus.DELIVERED,
    EvaluationStatus.WON,
}
_SYNCING_LEADS: ContextVar[frozenset[str]] = ContextVar(
    "itrix_progression_syncing_leads", default=frozenset()
)


@dataclass(frozen=True)
class ProgressionState:
    current_marketing_stage: str
    astop_verified_value_gate: bool
    alpha_compute_gate: bool
    alpha_core_gate: bool
    next_best_action: str


def _latest(evaluations, package):
    return next((item for item in evaluations if item.pkg == package), None)


def derive_progression_state(lead: Lead) -> ProgressionState:
    """Derive current gate/state truth from governed records without mutating anything."""
    astop = ASTOPEngagement.objects.filter(lead=lead).first()
    evaluations = list(Evaluation.objects.filter(lead=lead).order_by("-created_at"))
    compute = _latest(evaluations, EvaluationPackage.COMPUTE)
    core = _latest(evaluations, EvaluationPackage.CORE)

    astop_verified = bool(
        astop
        and astop.has_verified_value
        and controlled_evaluation_proof_gate(astop).allowed
    )

    compute_gate_allowed = False
    if compute is not None:
        compute_gate_allowed = alpha_compute_gate(
            lead,
            separate_workload=compute.separate_workload,
            technical_route=compute.technical_route,
        ).allowed

    core_gate_allowed = bool(
        compute is not None
        and compute_gate_allowed
        and alpha_core_gate(compute).allowed
    )

    active_core = core is not None and core.status in _NON_TERMINAL_PRODUCT_STATUSES
    active_compute = compute is not None and compute.status in _NON_TERMINAL_PRODUCT_STATUSES
    active_astop = astop is not None and astop.stage != ASTOPStage.CLOSED

    if active_core:
        stage = CommercialStage.ALPHA_CORE
    elif active_compute:
        stage = CommercialStage.ALPHA_COMPUTE
    elif active_astop:
        stage = CommercialStage.ASTOP
    elif lead.current_marketing_stage in {CommercialStage.DISCOVERY, CommercialStage.SALES_PLATFORM}:
        stage = lead.current_marketing_stage
    else:
        stage = CommercialStage.DISCOVERY

    if active_core:
        next_action = "progress_alpha_core_opportunity" if core_gate_allowed else "resolve_alpha_core_gate"
    elif compute is not None:
        if not compute_gate_allowed:
            next_action = "resolve_alpha_compute_gate"
        elif not core_gate_allowed:
            next_action = "complete_alpha_core_case"
        else:
            next_action = "open_alpha_core_opportunity"
    elif astop is not None:
        next_action = "open_alpha_compute_assessment" if astop_verified else "complete_astop_verified_value"
    else:
        next_action = "continue_discovery"

    return ProgressionState(
        current_marketing_stage=stage,
        astop_verified_value_gate=astop_verified,
        alpha_compute_gate=compute_gate_allowed,
        alpha_core_gate=core_gate_allowed,
        next_best_action=next_action,
    )


def is_syncing(lead_id) -> bool:
    return str(lead_id) in _SYNCING_LEADS.get()


def _actor_name(by) -> str:
    return getattr(by, "display_name", "") or getattr(by, "email", "") or "system"


@transaction.atomic
def sync_progression_state(lead: Lead, *, by=None, audit: bool = True) -> tuple[ProgressionState, bool]:
    """Persist the derived denormalized state iff it changed; repeated sync is idempotent."""
    locked = Lead.objects.select_for_update().get(pk=lead.pk)
    state = derive_progression_state(locked)
    progress = dict(locked.commercial_progress or {})
    desired = {
        "astop_verified_value_gate": state.astop_verified_value_gate,
        "alpha_compute_gate": state.alpha_compute_gate,
        "alpha_core_gate": state.alpha_core_gate,
        "next_best_action": state.next_best_action,
    }
    changed = (
        locked.current_marketing_stage != state.current_marketing_stage
        or any(progress.get(key) != value for key, value in desired.items())
    )
    if not changed:
        return state, False

    previous_stage = locked.current_marketing_stage
    previous_action = progress.get("next_best_action")
    progress.update(desired)
    locked.current_marketing_stage = state.current_marketing_stage
    locked.commercial_progress = progress

    current = _SYNCING_LEADS.get()
    token = _SYNCING_LEADS.set(current | {str(locked.pk)})
    try:
        locked.save(update_fields=["current_marketing_stage", "commercial_progress", "updated_at"])
    finally:
        _SYNCING_LEADS.reset(token)

    if audit:
        LeadActivity.objects.create(
            lead=locked,
            type=LeadActivity.ActivityType.STATUS_CHANGE,
            label="Governed ASTOP/ALPHA progression state synchronized.",
            by=by,
            by_name=_actor_name(by),
            meta={
                "domain": "cross_product_progression",
                "from_stage": previous_stage,
                "to_stage": state.current_marketing_stage,
                "from_next_best_action": previous_action,
                "to_next_best_action": state.next_best_action,
                "astop_verified_value_gate": state.astop_verified_value_gate,
                "alpha_compute_gate": state.alpha_compute_gate,
                "alpha_core_gate": state.alpha_core_gate,
            },
        )
    return state, True


def customer_safe_progression_state(lead: Lead) -> dict:
    """High-level customer/workspace projection; no gate rationale or IWL/risk detail."""
    state = derive_progression_state(lead)
    return {
        "currentMarketingStage": state.current_marketing_stage,
        "astopVerified": state.astop_verified_value_gate,
        "alphaComputeReady": state.alpha_compute_gate,
        "alphaCoreReady": state.alpha_core_gate,
        "nextBestAction": state.next_best_action,
    }
