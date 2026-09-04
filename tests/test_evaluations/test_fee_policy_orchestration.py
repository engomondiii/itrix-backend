"""Orchestration-level ALPHA fee-policy regressions."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.evaluations.services.fee_policy_orchestrator import (
    AUDIT_DOMAIN,
    orchestrate_assessment_fee_policy,
)
from apps.leads.models import ASTOPEngagement, ASTOPStage, LeadActivity, TrustStatus
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _qualified_lead():
    lead = LeadFactory(
        business_unit="Observation platform",
        sponsor="Executive sponsor",
        compute_bottleneck="Decision-time observation cost",
        workload_type="Agent observation workflow",
        trust_status=TrustStatus.PASS,
        trust_screening={"protection_acceptance": True},
        commercial_progress={"economic_relevance": "material", "seriousness": "qualified"},
    )
    now = timezone.now()
    ClientFactory(
        lead=lead,
        identity_verified_at=now,
        organization_verified_at=now,
        nda_signed=True,
        nda_signed_at=now,
    )
    ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.VERIFY_EXPAND,
        qualification_context={
            "business_unit": "Observation platform",
            "observation_problem": "Decision-time observation cost",
            "candidate_workflow": "Agent observation workflow",
            "economic_relevance": "material",
            "sponsor": "Executive sponsor",
            "seriousness": "qualified",
            "protection_fit": True,
        },
        evaluation_agreement="Controlled evaluation agreement",
        evaluation_scope={
            "workload": "Representative agent workload",
            "observation_behavior": "Observe decision-time usage",
            "model_or_controller": "Controller A",
            "workflow": "Agent observation workflow",
        },
        baseline={"measurement_window": "versioned controlled baseline window"},
        decision_fidelity={"status": "passed"},
        measured_savings={"value": 10, "provenance": "controlled measurement"},
        estimated_savings={"value": None, "provenance": "not estimated"},
        evaluation_result={"status": "passed", "reproducible": True},
        security_result={"status": "passed"},
        integration_feasibility={"status": "passed"},
        lo_scope={"field_of_use": "agent observation"},
        lo_executed_at=now,
        entitlement_status="active",
        controlled_build_id="build-verified",
        attribution_id="attr-verified",
        verified_value={"status": "verified", "basis": "controlled proof"},
    )
    return lead


def _create_assessment(*, standard_fee=Decimal("1000")):
    lead = _qualified_lead()
    return Evaluation.objects.create(
        lead=lead,
        lead_name="Buyer",
        company=lead.company,
        pkg=EvaluationPackage.COMPUTE,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
        standard_assessment_fee=standard_fee,
    )


def _audit(ev):
    return LeadActivity.objects.get(
        lead=ev.lead,
        meta__domain=AUDIT_DOMAIN,
        meta__evaluation_id=str(ev.id),
    )


def test_new_qualified_assessment_autonomously_records_paid_default_when_policy_criteria_absent(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {}

    ev = _create_assessment()
    ev.refresh_from_db()

    assert ev.ai_waiver_decision == WaiverType.NONE
    assert ev.waiver_type == WaiverType.NONE
    assert ev.customer_fee_status == "paid_default_pending_quote"
    activity = _audit(ev)
    assert activity.meta["decision_source"] == "paid_default"
    assert activity.meta["ai_decision"] == WaiverType.NONE
    assert activity.meta["iwl_override_window"] == "open"


def test_configured_full_waiver_is_applied_only_through_existing_deterministic_policy(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["full"],
        "policy_reference": "governed-policy-v1",
        "automatic_decision": {
            "waiver_type": "full",
            "reason": "Configured delegated policy decision.",
        },
    }

    ev = _create_assessment()
    ev.refresh_from_db()

    assert ev.ai_waiver_decision == WaiverType.FULL
    assert ev.customer_fee_status == "waiver_pending_finalization"
    activity = _audit(ev)
    assert activity.meta["decision_source"] == "configured_policy"
    assert activity.meta["policy_reference"] == "governed-policy-v1"


def test_configured_partial_waiver_uses_exact_configured_amount_not_model_generated_value(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["partial"],
        "max_partial_percentage": "30",
        "automatic_decision": {
            "waiver_type": "partial",
            "percentage": "25",
            "reason": "Configured bounded partial waiver.",
        },
    }

    ev = _create_assessment()
    ev.refresh_from_db()

    assert ev.ai_waiver_decision == WaiverType.PARTIAL
    assert ev.waiver_percentage_or_amount == {"percentage": "25"}


def test_invalid_or_over_limit_automatic_policy_fails_to_paid_default(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["partial"],
        "max_partial_percentage": "20",
        "automatic_decision": {
            "waiver_type": "partial",
            "percentage": "80",
            "reason": "Out of delegated bounds.",
        },
    }

    ev = _create_assessment()
    ev.refresh_from_db()

    assert ev.ai_waiver_decision == WaiverType.NONE
    assert ev.customer_fee_status == "paid_default_pending_quote"


def test_orchestration_is_idempotent_and_does_not_duplicate_audit(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {}
    ev = _create_assessment()

    result = orchestrate_assessment_fee_policy(ev)

    assert result.changed is False
    assert LeadActivity.objects.filter(
        lead=ev.lead,
        meta__domain=AUDIT_DOMAIN,
        meta__evaluation_id=str(ev.id),
    ).count() == 1


def test_orchestration_records_safe_gate_state_without_exposing_policy_criteria(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["full"],
        "policy_reference": "internal-policy-ref",
        "protected_criteria": {"do_not_expose": "secret commercial rubric"},
        "automatic_decision": {"waiver_type": "full", "reason": "Configured outcome."},
    }
    ev = _create_assessment()
    activity = _audit(ev)

    serialized_meta = str(activity.meta)
    assert "secret commercial rubric" not in serialized_meta
    assert "protected_criteria" not in serialized_meta
    assert ev.lead.commercial_progress["alpha_fee_policy_recorded"] is True
    assert ev.lead.commercial_progress["alpha_fee_policy_decision"] == WaiverType.FULL
