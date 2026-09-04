"""Current v2.3/v3.5 product-progression and assessment governance.

The ten-state relationship journey remains authoritative. This module owns the
commercial gates layered on top of it: verified-counterparty resolution, controlled
ASTOP progression/proof, ALPHA Compute assessment eligibility and fee treatment, and
the later ALPHA Core evidence gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationPackage, TechnicalRoute, WaiverType
from apps.leads.models import (
    ASTOPEngagement,
    ASTOPStage,
    CommercialStage,
    Lead,
    TrustStatus,
)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CounterpartyResolution:
    """Derived verification state for the Client explicitly linked to this Lead.

    No organization/company/domain string matching is performed here. The existing
    ``Client.lead`` OneToOne relation is the identity binding; the Client verification
    timestamps are the verification authority.
    """

    state: str
    client: object | None
    reasons: tuple[str, ...]
    human_review_required: bool = False


COUNTERPARTY_VERIFIED = "VERIFIED"
COUNTERPARTY_PENDING = "PENDING"
COUNTERPARTY_UNVERIFIED = "UNVERIFIED"
COUNTERPARTY_REJECTED = "REJECTED"

_AST0P_SEQUENCE = (
    ASTOPStage.IDENTIFY_QUALIFY,
    ASTOPStage.NDA_BRIEFING,
    ASTOPStage.CONTROLLED_EVALUATION,
    ASTOPStage.LO_DEPLOYMENT,
    ASTOPStage.VERIFY_EXPAND,
)
_PASS_STATUSES = {"pass", "passed", "validated", "verified", "successful", "success"}
_NOT_REQUIRED_STATUSES = {"not_required", "not-required", "n/a", "na"}
_ACTIVE_ENTITLEMENT_STATUSES = {"active", "authorized", "enabled"}
_BLOCKING_REVOCATION_STATUSES = {"revoked", "revoking", "suspended", "blocked"}


def _truthy_text(value) -> bool:
    return bool(str(value or "").strip())


def _present(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if value is None or value is False:
        return False
    return bool(value) or value == 0


def _normalised_status(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    raw = payload.get("status")
    if raw is None:
        raw = payload.get("result")
    return str(raw or "").strip().lower()


def _status_passes(payload, *, allow_not_required: bool = False) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("passed") is True or payload.get("verified") is True:
        return True
    status = _normalised_status(payload)
    if status in _PASS_STATUSES:
        return True
    return allow_not_required and status in _NOT_REQUIRED_STATUSES


def _unique_reasons(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def resolve_verified_counterparty(lead: Lead) -> CounterpartyResolution:
    """Resolve verified account/entity state from the existing authoritative link.

    ``Client.lead`` is the stable identity binding. Submitted Lead/Client organization
    text, corporate-domain strings and claimed identity are deliberately not accepted as
    verification evidence.
    """
    from apps.clients.models import Client

    client = Client.objects.filter(lead=lead).first()
    reasons: list[str] = []

    if lead.trust_status == TrustStatus.REJECT:
        return CounterpartyResolution(
            COUNTERPARTY_REJECTED,
            client,
            ("trust_rejected",),
            human_review_required=False,
        )
    if lead.trust_status == TrustStatus.REVIEW:
        return CounterpartyResolution(
            COUNTERPARTY_PENDING,
            client,
            ("trust_review_required",),
            human_review_required=True,
        )

    if client is None:
        reasons.append("verified_client_account_required")
        state = COUNTERPARTY_UNVERIFIED
    elif not client.is_active:
        reasons.append("active_client_account_required")
        state = COUNTERPARTY_UNVERIFIED
    else:
        state = COUNTERPARTY_PENDING
        if client.identity_verified_at is None:
            reasons.append("verified_identity_required")
        if client.organization_verified_at is None:
            reasons.append("verified_organization_required")

    if lead.trust_status != TrustStatus.PASS:
        reasons.append("trust_screening_pass_required")

    if not reasons:
        return CounterpartyResolution(COUNTERPARTY_VERIFIED, client, ())
    return CounterpartyResolution(state, client, _unique_reasons(reasons))


def verified_counterparty_gate(lead: Lead) -> GateDecision:
    resolution = resolve_verified_counterparty(lead)
    return GateDecision(
        resolution.state == COUNTERPARTY_VERIFIED,
        resolution.reasons,
    )


def _qualification_reasons(lead: Lead, record: ASTOPEngagement) -> list[str]:
    reasons = list(verified_counterparty_gate(lead).reasons)
    context = record.qualification_context if isinstance(record.qualification_context, dict) else {}
    progress = lead.commercial_progress if isinstance(lead.commercial_progress, dict) else {}
    trust = lead.trust_screening if isinstance(lead.trust_screening, dict) else {}

    if not _truthy_text(lead.business_unit or context.get("business_unit")):
        reasons.append("business_unit_required")
    if not _truthy_text(
        context.get("observation_problem") or lead.compute_bottleneck or lead.primary_pain
    ):
        reasons.append("observation_problem_required")
    if not _truthy_text(context.get("candidate_workflow") or lead.workload_type):
        reasons.append("candidate_workflow_required")
    if not _present(context.get("economic_relevance") or progress.get("economic_relevance")):
        reasons.append("economic_relevance_required")
    if not _truthy_text(lead.sponsor or context.get("sponsor") or progress.get("sponsor")):
        reasons.append("sponsor_required")
    if not _present(context.get("seriousness") or progress.get("seriousness")):
        reasons.append("seriousness_required")
    protection_fit = (
        context.get("protection_fit")
        or progress.get("protection_fit")
        or trust.get("protection_acceptance") is True
    )
    if not _present(protection_fit):
        reasons.append("protection_fit_required")
    return list(_unique_reasons(reasons))


def _nda_is_signed(lead: Lead, client=None) -> bool:
    """Agreement protection only; this never substitutes for content authorization."""
    from apps.nda.models import NDARecord, NDAStatus

    if NDARecord.objects.filter(
        lead=lead,
        status=NDAStatus.SIGNED,
        signed_at__isnull=False,
    ).exists():
        return True
    return bool(
        client is not None
        and getattr(client, "nda_signed", False)
        and getattr(client, "nda_signed_at", None) is not None
    )


def _controlled_entry_reasons(lead: Lead, record: ASTOPEngagement) -> list[str]:
    reasons = _qualification_reasons(lead, record)
    resolution = resolve_verified_counterparty(lead)
    if not _nda_is_signed(lead, resolution.client):
        reasons.append("signed_nda_required")
    if not _truthy_text(record.evaluation_agreement):
        reasons.append("evaluation_agreement_required")
    if not isinstance(record.evaluation_scope, dict) or not record.evaluation_scope:
        reasons.append("evaluation_scope_required")
    return list(_unique_reasons(reasons))


def _scope_value(scope: dict, *keys: str):
    for key in keys:
        if _present(scope.get(key)):
            return scope.get(key)
    return None


def _metric_value(payload) -> tuple[bool, object | None]:
    """Return availability without ever treating numeric zero as missing."""
    if not isinstance(payload, dict) or "value" not in payload:
        return False, None
    value = payload.get("value")
    return value is not None, value


def _metric_has_provenance(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        _truthy_text(payload.get(key))
        for key in ("provenance", "source", "basis", "measurement_source")
    )


def controlled_evaluation_proof_gate(record: ASTOPEngagement) -> GateDecision:
    """Validate the governed proof required before ASTOP value may be verified."""
    reasons: list[str] = []
    scope = record.evaluation_scope if isinstance(record.evaluation_scope, dict) else {}
    baseline = record.baseline if isinstance(record.baseline, dict) else {}

    if not _scope_value(scope, "workload", "qualifying_workload"):
        reasons.append("proof_workload_required")
    if not _scope_value(scope, "observation_behavior", "observation"):
        reasons.append("observation_behavior_required")
    if not _scope_value(scope, "model_or_controller", "controller", "model"):
        reasons.append("model_or_controller_required")
    if not _scope_value(scope, "workflow", "candidate_workflow"):
        reasons.append("proof_workflow_required")
    if not _scope_value(baseline, "measurement_window", "baseline_window", "window"):
        reasons.append("baseline_measurement_window_required")

    if not _status_passes(record.decision_fidelity):
        reasons.append("decision_fidelity_required")

    measured_available, _measured_value = _metric_value(record.measured_savings)
    estimated_available, _estimated_value = _metric_value(record.estimated_savings)
    if measured_available and not _metric_has_provenance(record.measured_savings):
        reasons.append("measured_provenance_required")
    if estimated_available and not _metric_has_provenance(record.estimated_savings):
        reasons.append("estimated_provenance_required")
    # Estimated evidence remains estimated. It can accompany a result but cannot by
    # itself become a verified-value claim.
    if not measured_available:
        reasons.append("measured_value_required_for_verified_value")

    if not _status_passes(record.security_result, allow_not_required=True):
        reasons.append("security_result_required")
    if not _status_passes(record.integration_feasibility, allow_not_required=True):
        reasons.append("integration_result_required")

    result = record.evaluation_result if isinstance(record.evaluation_result, dict) else {}
    if not _status_passes(result):
        reasons.append("successful_evaluation_result_required")
    reproducible = result.get("reproducible") is True or _status_passes(
        result.get("reproducibility") if isinstance(result.get("reproducibility"), dict) else {}
    )
    if not reproducible:
        reasons.append("reproducibility_required")

    return GateDecision(not reasons, _unique_reasons(reasons))


def _evaluation_claims_success(record: ASTOPEngagement) -> bool:
    if bool(record.verified_value):
        return True
    result = record.evaluation_result if isinstance(record.evaluation_result, dict) else {}
    return _status_passes(result) or result.get("verified") is True


def _production_entitlement_reasons(record: ASTOPEngagement) -> list[str]:
    reasons: list[str] = []
    if record.lo_executed_at is None:
        reasons.append("executed_license_out_required")
    if not isinstance(record.lo_scope, dict) or not record.lo_scope:
        reasons.append("license_out_scope_required")

    entitlement_status = str(record.entitlement_status or "").strip().lower()
    if entitlement_status not in _ACTIVE_ENTITLEMENT_STATUSES:
        reasons.append("active_entitlement_required")
    if record.entitlement_expires_at is not None and record.entitlement_expires_at <= timezone.now():
        reasons.append("entitlement_expired")
    if str(record.revocation_status or "").strip().lower() in _BLOCKING_REVOCATION_STATUSES:
        reasons.append("entitlement_revoked_or_suspended")
    if not _truthy_text(record.controlled_build_id):
        reasons.append("controlled_build_required")
    if not _truthy_text(record.attribution_id):
        reasons.append("attribution_required")
    return list(_unique_reasons(reasons))


def _lo_entry_reasons(lead: Lead, record: ASTOPEngagement) -> list[str]:
    reasons = _controlled_entry_reasons(lead, record)
    reasons.extend(controlled_evaluation_proof_gate(record).reasons)
    return list(_unique_reasons(reasons))


def _verify_expand_reasons(lead: Lead, record: ASTOPEngagement) -> list[str]:
    reasons = _lo_entry_reasons(lead, record)
    reasons.extend(_production_entitlement_reasons(record))
    if not record.verified_value:
        reasons.append("verified_value_required")
    return list(_unique_reasons(reasons))


def _transition_reasons(current: str, target: str) -> list[str]:
    if target == current:
        return []
    if target == ASTOPStage.CLOSED:
        return []
    if current == ASTOPStage.CLOSED:
        return ["closed_astop_engagement_cannot_reopen"]
    try:
        current_index = _AST0P_SEQUENCE.index(current)
        target_index = _AST0P_SEQUENCE.index(target)
    except ValueError:
        return ["invalid_astop_transition"]
    if target_index != current_index + 1:
        return ["sequential_astop_transition_required"]
    return []


def _stage_gate_reasons(lead: Lead, record: ASTOPEngagement, target: str) -> list[str]:
    if target in {ASTOPStage.IDENTIFY_QUALIFY, ASTOPStage.CLOSED}:
        return []
    if target == ASTOPStage.NDA_BRIEFING:
        return _qualification_reasons(lead, record)
    if target == ASTOPStage.CONTROLLED_EVALUATION:
        return _controlled_entry_reasons(lead, record)
    if target == ASTOPStage.LO_DEPLOYMENT:
        return _lo_entry_reasons(lead, record)
    if target == ASTOPStage.VERIFY_EXPAND:
        return _verify_expand_reasons(lead, record)
    return ["invalid_astop_stage"]


def _active_entitlement_requested(record: ASTOPEngagement) -> bool:
    return str(record.entitlement_status or "").strip().lower() in _ACTIVE_ENTITLEMENT_STATUSES


@transaction.atomic
def apply_astop_progress(lead: Lead, *, stage: str, values: dict | None = None) -> ASTOPEngagement:
    """Apply one governed ASTOP update; this is the only progression writer."""
    record = ASTOPEngagement.objects.select_for_update().filter(lead=lead).first()
    if record is None:
        record = ASTOPEngagement(lead=lead)

    current = record.stage
    for field, value in (values or {}).items():
        setattr(record, field, value)
    record.stage = stage

    reasons = _transition_reasons(current, stage)
    reasons.extend(_stage_gate_reasons(lead, record, stage))

    # Draft/in-progress Controlled Evaluation may be incomplete. Once the payload claims
    # success/value, however, the complete proof contract becomes mandatory immediately.
    if stage == ASTOPStage.CONTROLLED_EVALUATION and _evaluation_claims_success(record):
        reasons.extend(controlled_evaluation_proof_gate(record).reasons)

    if record.verified_value and stage != ASTOPStage.VERIFY_EXPAND:
        reasons.append("verified_value_requires_verify_expand")

    # LO & Deployment may be entered while an LO is being prepared/negotiated. Only an
    # ACTIVE production entitlement requires execution at that stage.
    if stage == ASTOPStage.LO_DEPLOYMENT and _active_entitlement_requested(record):
        reasons.extend(_production_entitlement_reasons(record))

    reasons = list(_unique_reasons(reasons))
    if reasons:
        raise ValueError("astop_progression_gate:" + ",".join(reasons))

    record.save()
    lead.current_marketing_stage = CommercialStage.ASTOP
    lead.commercial_progress = {
        **(lead.commercial_progress or {}),
        "astop_stage": stage,
        "astop_verified_value_gate": record.has_verified_value,
    }
    lead.save(update_fields=["current_marketing_stage", "commercial_progress", "updated_at"])
    return record


def alpha_compute_gate(
    lead: Lead,
    *,
    separate_workload: str,
    technical_route: str = "none",
) -> GateDecision:
    """Fail closed on substantive ALPHA gates; fee treatment is never a substitute."""
    reasons: list[str] = list(verified_counterparty_gate(lead).reasons)
    astop = ASTOPEngagement.objects.filter(lead=lead).first()
    resolution = resolve_verified_counterparty(lead)

    if not _nda_is_signed(lead, resolution.client):
        reasons.append("signed_nda_required")
    if astop is None or not astop.has_verified_value:
        reasons.append("astop_verified_value_required")
    else:
        reasons.extend(controlled_evaluation_proof_gate(astop).reasons)
        reasons.extend(_production_entitlement_reasons(astop))

    if not _truthy_text(separate_workload):
        reasons.append("separate_workload_required")
    progress = lead.commercial_progress or {}
    if not _truthy_text(progress.get("economic_relevance")):
        reasons.append("economic_relevance_required")
    if not (_truthy_text(lead.sponsor) or _truthy_text(progress.get("sponsor"))):
        reasons.append("sponsor_required")
    if technical_route not in set(TechnicalRoute.values) - {TechnicalRoute.NONE}:
        reasons.append("eligibility_hypothesis_required")
    return GateDecision(not reasons, _unique_reasons(reasons))


@transaction.atomic
def create_alpha_compute_assessment(
    lead: Lead,
    *,
    separate_workload: str,
    technical_route: str,
    scope: str = "",
) -> Evaluation:
    gate = alpha_compute_gate(
        lead,
        separate_workload=separate_workload,
        technical_route=technical_route,
    )
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


def _evaluation_substantive_gate(evaluation: Evaluation) -> GateDecision:
    if evaluation.pkg != EvaluationPackage.COMPUTE:
        return GateDecision(True, ())
    return alpha_compute_gate(
        evaluation.lead,
        separate_workload=evaluation.separate_workload,
        technical_route=evaluation.technical_route,
    )


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
    """Record delegated fee treatment without ever waiving substantive ALPHA gates."""
    policy = _policy()
    requested = waiver_type if waiver_type in WaiverType.values else WaiverType.NONE

    if requested != WaiverType.NONE:
        substantive = _evaluation_substantive_gate(evaluation)
        if not substantive.allowed:
            requested = WaiverType.NONE
            reason = "Substantive assessment gates are not satisfied."

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
        "waiver_pending_finalization"
        if requested != WaiverType.NONE
        else "paid_default_pending_quote"
    )
    evaluation.save(
        update_fields=[
            "ai_waiver_decision",
            "waiver_type",
            "waiver_percentage_or_amount",
            "waiver_reason",
            "waiver_expiry",
            "customer_fee_status",
            "updated_at",
        ]
    )
    return evaluation


@transaction.atomic
def record_iwl_override(
    evaluation: Evaluation,
    *,
    waiver_type: str,
    reason: str,
    final_fee=None,
) -> Evaluation:
    """Apply superior IWL fee authority without bypassing substantive product gates."""
    if evaluation.fee_finalized_at:
        raise ValueError("assessment_fee_already_finalized")
    if waiver_type not in WaiverType.values:
        raise ValueError("invalid_waiver_type")
    if waiver_type != WaiverType.NONE:
        substantive = _evaluation_substantive_gate(evaluation)
        if not substantive.allowed:
            raise ValueError("alpha_substantive_gate:" + ",".join(substantive.reasons))
    evaluation.iwl_override_status = waiver_type
    evaluation.iwl_override_applied = True
    evaluation.iwl_override_reason = reason.strip()
    evaluation.final_assessment_fee = _decimal(final_fee)
    evaluation.save(
        update_fields=[
            "iwl_override_status",
            "iwl_override_applied",
            "iwl_override_reason",
            "final_assessment_fee",
            "updated_at",
        ]
    )
    return evaluation


@transaction.atomic
def finalize_assessment_fee(evaluation: Evaluation) -> Evaluation:
    if evaluation.fee_finalized_at:
        return evaluation
    override = evaluation.iwl_override_status if evaluation.iwl_override_applied else None
    chosen = (
        override
        if override in WaiverType.values
        else (evaluation.ai_waiver_decision or WaiverType.NONE)
    )

    if chosen != WaiverType.NONE:
        substantive = _evaluation_substantive_gate(evaluation)
        if not substantive.allowed:
            chosen = WaiverType.NONE
            evaluation.final_authority = "governance"
        else:
            evaluation.final_authority = "iwl" if evaluation.iwl_override_applied else "ai"
    else:
        evaluation.final_authority = "iwl" if evaluation.iwl_override_applied else "ai"

    if chosen == WaiverType.FULL:
        evaluation.final_assessment_fee = Decimal("0")
        evaluation.customer_fee_status = "waived"
    elif chosen == WaiverType.PARTIAL:
        if evaluation.final_assessment_fee is None and evaluation.standard_assessment_fee is not None:
            details = evaluation.waiver_percentage_or_amount or {}
            pct = _decimal(details.get("percentage"))
            amt = _decimal(details.get("amount"))
            if pct is not None:
                evaluation.final_assessment_fee = max(
                    Decimal("0"),
                    evaluation.standard_assessment_fee
                    * (Decimal("1") - pct / Decimal("100")),
                )
            elif amt is not None:
                evaluation.final_assessment_fee = max(
                    Decimal("0"),
                    evaluation.standard_assessment_fee - amt,
                )
        evaluation.customer_fee_status = "partially_waived"
    else:
        if evaluation.final_assessment_fee is None:
            evaluation.final_assessment_fee = evaluation.standard_assessment_fee
        evaluation.customer_fee_status = "paid"
    evaluation.fee_finalized_at = timezone.now()
    evaluation.save(
        update_fields=[
            "final_authority",
            "final_assessment_fee",
            "customer_fee_status",
            "fee_finalized_at",
            "updated_at",
        ]
    )
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
