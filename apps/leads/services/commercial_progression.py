"""Current v2.3/v3.5 product-progression and assessment governance.

The ten-state relationship journey remains authoritative.  This module adds only the
product-commercial facts that the September 2026 sources require: controlled ASTOP proof,
a separate ALPHA Compute opportunity, delegated assessment-fee treatment and the later
ALPHA Core evidence gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationPackage, TechnicalRoute, WaiverType
from apps.leads.models import ASTOPEngagement, ASTOPStage, CommercialStage, Lead


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...]


def _truthy_text(value) -> bool:
    return bool(str(value or "").strip())


def alpha_compute_gate(lead: Lead, *, separate_workload: str, technical_route: str = "none") -> GateDecision:
    """Fail closed unless ASTOP value is verified and a distinct Compute case exists."""
    reasons: list[str] = []
    astop = ASTOPEngagement.objects.filter(lead=lead).first()
    if astop is None or not astop.has_verified_value:
        reasons.append("astop_verified_value_required")
    if not _truthy_text(separate_workload):
        reasons.append("separate_workload_required")
    progress = lead.commercial_progress or {}
    if not _truthy_text(progress.get("economic_relevance")):
        reasons.append("economic_relevance_required")
    if not (_truthy_text(lead.sponsor) or _truthy_text(progress.get("sponsor"))):
        reasons.append("sponsor_required")
    if technical_route not in set(TechnicalRoute.values) - {TechnicalRoute.NONE}:
        reasons.append("eligibility_hypothesis_required")
    return GateDecision(not reasons, tuple(reasons))


@transaction.atomic
def create_alpha_compute_assessment(
    lead: Lead,
    *,
    separate_workload: str,
    technical_route: str,
    scope: str = "",
) -> Evaluation:
    gate = alpha_compute_gate(lead, separate_workload=separate_workload, technical_route=technical_route)
    if not gate.allowed:
        raise ValueError("alpha_compute_gate:" + ",".join(gate.reasons))

    existing = Evaluation.objects.filter(
        lead=lead,
        pkg=EvaluationPackage.COMPUTE,
        status__in=["proposed", "in_progress"],
    ).first()
    if existing:
        return existing

    evaluation = Evaluation.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        pkg=EvaluationPackage.COMPUTE,
        separate_workload=separate_workload.strip(),
        technical_route=technical_route,
        scope=scope.strip(),
        customer_fee_status="paid_default_pending_quote",
    )
    lead.current_marketing_stage = CommercialStage.ALPHA_COMPUTE
    lead.commercial_progress = {
        **(lead.commercial_progress or {}),
        "astop_verified_value_gate": True,
        "alpha_compute_gate": True,
        "next_best_action": "alpha_compute_assessment",
    }
    lead.save(update_fields=["current_marketing_stage", "commercial_progress", "updated_at"])
    return evaluation


def _policy() -> dict:
    policy = getattr(settings, "ALPHA_ASSESSMENT_FEE_POLICY", None)
    return policy if isinstance(policy, dict) else {}


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@transaction.atomic
def record_ai_fee_decision(
    evaluation: Evaluation,
    *,
    waiver_type: str,
    reason: str,
    percentage: Decimal | int | str | None = None,
    amount: Decimal | int | str | None = None,
    expiry=None,
) -> Evaluation:
    """Record delegated AI treatment, but only inside configured IWL policy.

    In the absence of explicit configured criteria, the source-mandated safe default is
    the standard paid assessment.  No thresholds or percentages are invented here.
    """
    policy = _policy()
    requested = waiver_type if waiver_type in WaiverType.values else WaiverType.NONE
    allowed_types = set(policy.get("allowed_waiver_types") or []) if policy.get("enabled") else set()
    if requested != WaiverType.NONE and requested not in allowed_types:
        requested = WaiverType.NONE
        reason = reason or "No configured IWL policy authorizes a waiver for this assessment."

    pct = _decimal(percentage)
    amt = _decimal(amount)
    details: dict[str, str] = {}
    if requested == WaiverType.PARTIAL:
        max_pct = _decimal(policy.get("max_partial_percentage"))
        max_amt = _decimal(policy.get("max_partial_amount"))
        if pct is not None:
            if pct <= 0 or pct >= 100 or max_pct is None or pct > max_pct:
                requested = WaiverType.NONE
            else:
                details["percentage"] = str(pct)
        elif amt is not None:
            if amt <= 0 or max_amt is None or amt > max_amt:
                requested = WaiverType.NONE
            else:
                details["amount"] = str(amt)
        else:
            requested = WaiverType.NONE
    elif requested == WaiverType.FULL:
        details["full"] = "true"

    evaluation.ai_waiver_decision = requested
    evaluation.waiver_type = requested
    evaluation.waiver_percentage_or_amount = details if requested != WaiverType.NONE else {}
    evaluation.waiver_reason = reason.strip()
    evaluation.waiver_expiry = expiry
    evaluation.customer_fee_status = (
        "waiver_pending_finalization" if requested != WaiverType.NONE else "paid_default_pending_quote"
    )
    evaluation.save(update_fields=[
        "ai_waiver_decision", "waiver_type", "waiver_percentage_or_amount", "waiver_reason",
        "waiver_expiry", "customer_fee_status", "updated_at",
    ])
    return evaluation


@transaction.atomic
def record_iwl_override(
    evaluation: Evaluation,
    *,
    waiver_type: str,
    reason: str,
    final_fee=None,
) -> Evaluation:
    """Apply superior IWL authority before finalization; callers must be staff-authorized."""
    if evaluation.fee_finalized_at:
        raise ValueError("assessment_fee_already_finalized")
    if waiver_type not in WaiverType.values:
        raise ValueError("invalid_waiver_type")
    evaluation.iwl_override_status = waiver_type
    evaluation.iwl_override_applied = True
    evaluation.iwl_override_reason = reason.strip()
    evaluation.final_assessment_fee = _decimal(final_fee)
    evaluation.save(update_fields=[
        "iwl_override_status", "iwl_override_applied", "iwl_override_reason", "final_assessment_fee", "updated_at"
    ])
    return evaluation


@transaction.atomic
def finalize_assessment_fee(evaluation: Evaluation) -> Evaluation:
    if evaluation.fee_finalized_at:
        return evaluation
    override = evaluation.iwl_override_status if evaluation.iwl_override_applied else None
    chosen = override if override in WaiverType.values else (evaluation.ai_waiver_decision or WaiverType.NONE)
    evaluation.final_authority = "iwl" if evaluation.iwl_override_applied else "ai"
    if chosen == WaiverType.FULL:
        evaluation.final_assessment_fee = Decimal("0")
        evaluation.customer_fee_status = "waived"
    elif chosen == WaiverType.PARTIAL:
        # Finalization should produce a customer-usable fee when the standard fee and
        # delegated partial-waiver amount/percentage are both known. If either is
        # intentionally still unquoted, keep the final amount null and expose only the
        # governed partially-waived status.
        if evaluation.final_assessment_fee is None and evaluation.standard_assessment_fee is not None:
            details = evaluation.waiver_percentage_or_amount or {}
            pct = _decimal(details.get("percentage"))
            amt = _decimal(details.get("amount"))
            if pct is not None:
                evaluation.final_assessment_fee = max(
                    Decimal("0"),
                    evaluation.standard_assessment_fee * (Decimal("1") - pct / Decimal("100")),
                )
            elif amt is not None:
                evaluation.final_assessment_fee = max(Decimal("0"), evaluation.standard_assessment_fee - amt)
        evaluation.customer_fee_status = "partially_waived"
    else:
        if evaluation.final_assessment_fee is None:
            evaluation.final_assessment_fee = evaluation.standard_assessment_fee
        evaluation.customer_fee_status = "paid"
    evaluation.fee_finalized_at = timezone.now()
    evaluation.save(update_fields=[
        "final_authority", "final_assessment_fee", "customer_fee_status", "fee_finalized_at", "updated_at"
    ])
    return evaluation


def alpha_core_gate(evaluation: Evaluation) -> GateDecision:
    reasons: list[str] = []
    if evaluation.pkg != EvaluationPackage.COMPUTE or evaluation.proof_status != "validated":
        reasons.append("validated_software_proof_required")
    if not evaluation.hardware_value_case:
        reasons.append("incremental_hardware_value_required")
    if not _truthy_text(evaluation.hardware_target):
        reasons.append("hardware_target_required")
    if not _truthy_text(evaluation.hardware_economics):
        reasons.append("hardware_economics_required")
    if not _truthy_text(evaluation.hardware_sponsor):
        reasons.append("hardware_sponsor_required")
    return GateDecision(not reasons, tuple(reasons))
