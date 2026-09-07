"""Deterministic ALPHA assessment fee-policy orchestration.

This is the orchestration seam between a newly qualified ALPHA Compute assessment and the
existing governed fee-decision service. The model is never asked to invent policy
criteria, percentages or amounts: only values explicitly present in configuration can be
forwarded. When no automatic policy decision is configured, the result is an explicit
NO-waiver paid default.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.leads.models import LeadActivity


AUDIT_DOMAIN = "alpha_fee_policy"


@dataclass(frozen=True)
class FeePolicyOrchestrationResult:
    evaluation: Evaluation
    decision: str
    source: str
    changed: bool


def _policy() -> dict:
    value = getattr(settings, "ALPHA_ASSESSMENT_FEE_POLICY", None)
    return value if isinstance(value, dict) else {}


def _configured_decision(policy: dict) -> tuple[dict, str]:
    """Return only an explicit delegated decision; never derive commercial terms."""
    configured = policy.get("automatic_decision") if policy.get("enabled") else None
    if not isinstance(configured, dict):
        return {
            "waiver_type": WaiverType.NONE,
            "reason": "No configured automatic waiver criteria; paid assessment is the default.",
        }, "paid_default"

    waiver_type = configured.get("waiver_type")
    if waiver_type not in WaiverType.values:
        return {
            "waiver_type": WaiverType.NONE,
            "reason": "Configured automatic waiver decision is invalid; paid assessment is the default.",
        }, "paid_default"

    payload = {
        "waiver_type": waiver_type,
        "reason": str(configured.get("reason") or "Configured delegated fee policy decision.").strip(),
    }
    # A partial waiver must carry an exact configured percentage OR amount. The existing
    # deterministic service applies configured maxima; this orchestrator never calculates
    # one from conversation text or model output.
    if waiver_type == WaiverType.PARTIAL:
        if configured.get("percentage") not in (None, ""):
            payload["percentage"] = configured.get("percentage")
        elif configured.get("amount") not in (None, ""):
            payload["amount"] = configured.get("amount")
    if configured.get("expiry") is not None:
        payload["expiry"] = configured.get("expiry")
    return payload, "configured_policy"


def _already_recorded(evaluation: Evaluation) -> LeadActivity | None:
    return LeadActivity.objects.filter(
        lead=evaluation.lead,
        meta__domain=AUDIT_DOMAIN,
        meta__evaluation_id=str(evaluation.id),
    ).order_by("created_at").first()


def _actor_label() -> str:
    return "AI delegated policy"


@transaction.atomic
def orchestrate_assessment_fee_policy(evaluation: Evaluation) -> FeePolicyOrchestrationResult:
    """Record the delegated policy outcome once and leave the IWL override window open."""
    if evaluation.pkg != EvaluationPackage.COMPUTE:
        return FeePolicyOrchestrationResult(evaluation, WaiverType.NONE, "not_applicable", False)

    locked = Evaluation.objects.select_for_update().select_related("lead").get(pk=evaluation.pk)
    existing = _already_recorded(locked)
    if existing is not None:
        return FeePolicyOrchestrationResult(
            locked,
            str(existing.meta.get("ai_decision") or locked.ai_waiver_decision or WaiverType.NONE),
            str(existing.meta.get("decision_source") or "recorded"),
            False,
        )

    policy = _policy()
    payload, source = _configured_decision(policy)

    # Local import avoids creating a module-level cycle: commercial_progression creates
    # the assessment and owns the deterministic decision/finalization functions.
    from apps.leads.services.commercial_progression import record_ai_fee_decision

    locked = record_ai_fee_decision(locked, **payload)
    policy_reference = str(policy.get("policy_reference") or "").strip()
    LeadActivity.objects.create(
        lead=locked.lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        label=f"ALPHA assessment fee policy recorded: {locked.ai_waiver_decision}.",
        by=None,
        by_name=_actor_label(),
        meta={
            "domain": AUDIT_DOMAIN,
            "evaluation_id": str(locked.id),
            "ai_decision": locked.ai_waiver_decision,
            "decision_source": source,
            "policy_reference": policy_reference,
            # The window is the existing not-finalized state. No parallel workflow/state
            # machine is introduced; record_iwl_override already fails after finalization.
            "iwl_override_window": "open" if locked.fee_finalized_at is None else "closed",
        },
    )
    progress = dict(locked.lead.commercial_progress or {})
    progress.update(
        {
            "alpha_fee_policy_recorded": True,
            "alpha_fee_policy_evaluation_id": str(locked.id),
            "alpha_fee_policy_decision": locked.ai_waiver_decision,
        }
    )
    locked.lead.commercial_progress = progress
    locked.lead.save(update_fields=["commercial_progress", "updated_at"])
    return FeePolicyOrchestrationResult(locked, locked.ai_waiver_decision, source, True)
