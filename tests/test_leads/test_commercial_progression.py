"""Focused September-2026 ASTOP → ALPHA commercial-governance regressions."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.leads.models import ASTOPEngagement, ASTOPStage, TrustStatus
from apps.leads.serializers import ASTOPProgressSerializer
from apps.leads.services.commercial_progression import (
    alpha_compute_gate,
    alpha_core_gate,
    apply_astop_progress,
    controlled_evaluation_proof_gate,
    finalize_assessment_fee,
    record_ai_fee_decision,
    record_iwl_override,
    resolve_verified_counterparty,
)
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, DEFAULT_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def _login(api: APIClient, user):
    response = api.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        format="json",
    )
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")


def _verified_lead(*, trust_status=TrustStatus.PASS, nda=True):
    lead = LeadFactory(
        business_unit="Observation platform",
        sponsor="Executive sponsor",
        compute_bottleneck="Decision-time observation cost",
        workload_type="Agent observation workflow",
        trust_status=trust_status,
        trust_screening={"protection_acceptance": True},
        commercial_progress={
            "economic_relevance": "material",
            "seriousness": "qualified",
        },
    )
    now = timezone.now()
    ClientFactory(
        lead=lead,
        identity_verified_at=now,
        organization_verified_at=now,
        nda_signed=nda,
        nda_signed_at=now if nda else None,
    )
    return lead


def _qualification_context():
    return {
        "business_unit": "Observation platform",
        "observation_problem": "Decision-time observation cost",
        "candidate_workflow": "Agent observation workflow",
        "economic_relevance": "material",
        "sponsor": "Executive sponsor",
        "seriousness": "qualified",
        "protection_fit": True,
    }


def _evaluation_scope():
    return {
        "workload": "Representative agent workload",
        "observation_behavior": "Observe decision-time token/tool usage",
        "model_or_controller": "Controlled controller A",
        "workflow": "Agent observation workflow",
    }


def _proof_values(*, measured_value=0, fidelity="passed"):
    return {
        "baseline": {"measurement_window": "versioned controlled baseline window"},
        "decision_fidelity": {"status": fidelity},
        "measured_savings": {
            "value": measured_value,
            "provenance": "controlled measurement",
        },
        "estimated_savings": {"value": None, "provenance": "not estimated"},
        "evaluation_result": {"status": "passed", "reproducible": True},
        "security_result": {"status": "passed"},
        "integration_feasibility": {"status": "passed"},
    }


def _verified_astop(lead):
    now = timezone.now()
    return ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.VERIFY_EXPAND,
        qualification_context=_qualification_context(),
        evaluation_agreement="Controlled evaluation agreement",
        evaluation_scope=_evaluation_scope(),
        lo_scope={"field_of_use": "agent observation"},
        lo_executed_at=now,
        entitlement_status="active",
        controlled_build_id="build-verified",
        attribution_id="attr-verified",
        verified_value={"status": "verified", "basis": "controlled proof"},
        **_proof_values(),
    )


def _governed_compute_evaluation(*, standard_fee=Decimal("1000")):
    lead = _verified_lead()
    _verified_astop(lead)
    return Evaluation.objects.create(
        lead=lead,
        lead_name="Buyer",
        pkg=EvaluationPackage.COMPUTE,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
        standard_assessment_fee=standard_fee,
    )


def test_existing_client_lead_link_is_the_verified_counterparty_authority():
    lead = _verified_lead()
    resolution = resolve_verified_counterparty(lead)
    assert resolution.state == "VERIFIED"
    assert resolution.client.lead_id == lead.id
    assert resolution.reasons == ()


def test_submitted_company_or_domain_never_substitutes_for_verified_client_entity():
    lead = LeadFactory(
        company="Claimed Corp",
        legal_entity="Claimed Corp Ltd",
        corporate_domain="claimed.example",
        trust_status=TrustStatus.PASS,
        trust_screening={"protection_acceptance": True},
        business_unit="Unit",
        sponsor="Sponsor",
        compute_bottleneck="Problem",
        workload_type="Workflow",
        commercial_progress={"economic_relevance": "material", "seriousness": "qualified"},
    )
    resolution = resolve_verified_counterparty(lead)
    assert resolution.state == "UNVERIFIED"
    assert "verified_client_account_required" in resolution.reasons


def test_unverified_entity_is_blocked_from_sensitive_astop_progression():
    lead = LeadFactory(
        trust_status=TrustStatus.PASS,
        business_unit="Unit",
        sponsor="Sponsor",
        compute_bottleneck="Problem",
        workload_type="Workflow",
        trust_screening={"protection_acceptance": True},
        commercial_progress={"economic_relevance": "material", "seriousness": "qualified"},
    )
    with pytest.raises(ValueError, match="verified_client_account_required"):
        apply_astop_progress(
            lead,
            stage=ASTOPStage.NDA_BRIEFING,
            values={"qualification_context": _qualification_context()},
        )


def test_verified_entity_is_allowed_when_other_qualification_gates_pass():
    lead = _verified_lead()
    record = apply_astop_progress(
        lead,
        stage=ASTOPStage.NDA_BRIEFING,
        values={"qualification_context": _qualification_context()},
    )
    assert record.stage == ASTOPStage.NDA_BRIEFING


@pytest.mark.parametrize("trust_status", [TrustStatus.REVIEW, TrustStatus.REJECT])
def test_review_and_reject_block_sensitive_astop_progression(trust_status):
    lead = _verified_lead(trust_status=trust_status)
    with pytest.raises(ValueError):
        apply_astop_progress(
            lead,
            stage=ASTOPStage.NDA_BRIEFING,
            values={"qualification_context": _qualification_context()},
        )


def test_review_and_reject_do_not_block_public_safe_identify_state_updates():
    for trust_status in (TrustStatus.REVIEW, TrustStatus.REJECT):
        lead = _verified_lead(trust_status=trust_status)
        record = apply_astop_progress(
            lead,
            stage=ASTOPStage.IDENTIFY_QUALIFY,
            values={"qualification_context": {"public_safe_note": "education only"}},
        )
        assert record.stage == ASTOPStage.IDENTIFY_QUALIFY


def test_stage_skipping_is_rejected_even_when_later_payload_is_complete():
    lead = _verified_lead()
    with pytest.raises(ValueError, match="sequential_astop_transition_required"):
        apply_astop_progress(
            lead,
            stage=ASTOPStage.CONTROLLED_EVALUATION,
            values={
                "qualification_context": _qualification_context(),
                "evaluation_agreement": "Agreement",
                "evaluation_scope": _evaluation_scope(),
            },
        )


def test_stage_prerequisites_are_enforced():
    lead = _verified_lead()
    lead.business_unit = ""
    lead.compute_bottleneck = ""
    lead.primary_pain = ""
    lead.workload_type = ""
    lead.commercial_progress = {}
    lead.sponsor = ""
    lead.save(
        update_fields=[
            "business_unit", "compute_bottleneck", "primary_pain", "workload_type",
            "commercial_progress", "sponsor", "updated_at",
        ]
    )
    with pytest.raises(ValueError) as exc:
        apply_astop_progress(lead, stage=ASTOPStage.NDA_BRIEFING, values={})
    text = str(exc.value)
    assert "business_unit_required" in text
    assert "observation_problem_required" in text
    assert "candidate_workflow_required" in text
    assert "economic_relevance_required" in text
    assert "sponsor_required" in text


def test_controlled_evaluation_requires_signed_nda_and_agreement():
    lead = _verified_lead(nda=False)
    apply_astop_progress(
        lead,
        stage=ASTOPStage.NDA_BRIEFING,
        values={"qualification_context": _qualification_context()},
    )
    with pytest.raises(ValueError) as exc:
        apply_astop_progress(
            lead,
            stage=ASTOPStage.CONTROLLED_EVALUATION,
            values={"evaluation_scope": _evaluation_scope()},
        )
    assert "signed_nda_required" in str(exc.value)
    assert "evaluation_agreement_required" in str(exc.value)


def test_lo_negotiation_stage_is_allowed_before_lo_execution():
    lead = _verified_lead()
    apply_astop_progress(
        lead,
        stage=ASTOPStage.NDA_BRIEFING,
        values={"qualification_context": _qualification_context()},
    )
    apply_astop_progress(
        lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        values={
            "evaluation_agreement": "Controlled evaluation agreement",
            "evaluation_scope": _evaluation_scope(),
        },
    )
    record = apply_astop_progress(
        lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
        values={**_proof_values(), "lo_scope": {"field_of_use": "agent observation"}},
    )
    assert record.stage == ASTOPStage.LO_DEPLOYMENT
    assert record.lo_executed_at is None


def test_production_entitlement_is_blocked_before_executed_lo():
    lead = _verified_lead()
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
        lo_scope={"field_of_use": "agent observation"},
        **_proof_values(),
    )
    with pytest.raises(ValueError, match="executed_license_out_required"):
        apply_astop_progress(
            lead,
            stage=ASTOPStage.LO_DEPLOYMENT,
            values={
                "entitlement_status": "active",
                "controlled_build_id": "build-1",
                "attribution_id": "attr-1",
            },
        )
    record.refresh_from_db()
    assert record.entitlement_status == ""


def test_incomplete_evaluation_cannot_become_verified_value():
    lead = _verified_lead()
    ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
    )
    with pytest.raises(ValueError) as exc:
        apply_astop_progress(
            lead,
            stage=ASTOPStage.CONTROLLED_EVALUATION,
            values={
                "evaluation_result": {"status": "passed", "reproducible": True},
                "verified_value": {"status": "verified"},
            },
        )
    assert "baseline_measurement_window_required" in str(exc.value)
    assert "verified_value_requires_verify_expand" in str(exc.value)


def test_fidelity_failure_blocks_verified_proof_progression():
    lead = _verified_lead()
    ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
    )
    with pytest.raises(ValueError, match="decision_fidelity_required"):
        apply_astop_progress(
            lead,
            stage=ASTOPStage.LO_DEPLOYMENT,
            values={**_proof_values(fidelity="failed"), "lo_scope": {"field": "x"}},
        )


def test_measured_zero_is_preserved_as_measured_zero():
    lead = _verified_lead()
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
    )
    record = apply_astop_progress(
        lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
        values={**_proof_values(measured_value=0), "lo_scope": {"field": "x"}},
    )
    assert record.measured_savings["value"] == 0
    assert controlled_evaluation_proof_gate(record).allowed is True


def test_null_stays_unavailable_and_is_never_normalized_to_zero():
    lead = _verified_lead()
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
    )
    record = apply_astop_progress(
        lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        values={"measured_savings": {"value": None}},
    )
    assert record.measured_savings["value"] is None
    assert "measured_value_required_for_verified_value" in controlled_evaluation_proof_gate(record).reasons


def test_estimated_value_remains_estimated_and_cannot_substitute_for_measurement():
    lead = _verified_lead()
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        qualification_context=_qualification_context(),
        evaluation_agreement="Agreement",
        evaluation_scope=_evaluation_scope(),
    )
    record = apply_astop_progress(
        lead,
        stage=ASTOPStage.CONTROLLED_EVALUATION,
        values={
            "measured_savings": {"value": None},
            "estimated_savings": {"value": 42, "provenance": "bounded estimate"},
        },
    )
    assert record.estimated_savings["value"] == 42
    assert record.measured_savings["value"] is None
    assert "measured_value_required_for_verified_value" in controlled_evaluation_proof_gate(record).reasons


def test_serializer_preserves_zero_null_and_separate_estimate_fields():
    serializer = ASTOPProgressSerializer(
        data={
            "stage": "controlled_evaluation",
            "measured_savings": {"value": 0, "provenance": "measurement"},
            "estimated_savings": {"value": None},
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["measured_savings"]["value"] == 0
    assert serializer.validated_data["estimated_savings"]["value"] is None


def test_alpha_compute_gate_requires_verified_astop_and_separate_workload():
    lead = _verified_lead()
    ASTOPEngagement.objects.create(lead=lead, stage=ASTOPStage.LO_DEPLOYMENT)
    decision = alpha_compute_gate(lead, separate_workload="", technical_route="axiom_tensor")
    assert decision.allowed is False
    assert "astop_verified_value_required" in decision.reasons
    assert "separate_workload_required" in decision.reasons


def test_alpha_compute_gate_allows_fully_governed_case():
    lead = _verified_lead()
    _verified_astop(lead)
    decision = alpha_compute_gate(
        lead,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
    )
    assert decision.allowed is True


def test_alpha_assessment_is_paid_by_default_and_ai_no_waiver_is_final_authority(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {}
    lead = LeadFactory()
    ev = Evaluation.objects.create(
        lead=lead,
        lead_name="Buyer",
        pkg=EvaluationPackage.COMPUTE,
        standard_assessment_fee=Decimal("1000"),
    )

    record_ai_fee_decision(ev, waiver_type=WaiverType.FULL, reason="Requested")
    ev.refresh_from_db()
    assert ev.ai_waiver_decision == WaiverType.NONE
    assert ev.customer_fee_status == "paid_default_pending_quote"

    finalize_assessment_fee(ev)
    ev.refresh_from_db()
    assert ev.final_authority == "ai"
    assert ev.final_assessment_fee == Decimal("1000")
    assert ev.customer_fee_status == "paid"


def test_full_fee_waiver_cannot_bypass_substantive_gates(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["full"],
    }
    lead = LeadFactory()
    ev = Evaluation.objects.create(
        lead=lead,
        lead_name="Buyer",
        pkg=EvaluationPackage.COMPUTE,
        separate_workload="Workload",
        technical_route="axiom_tensor",
    )
    record_ai_fee_decision(ev, waiver_type="full", reason="Strategic request")
    ev.refresh_from_db()
    assert ev.ai_waiver_decision == WaiverType.NONE
    assert ev.waiver_type == WaiverType.NONE
    assert ev.customer_fee_status == "paid_default_pending_quote"


def test_ai_full_and_partial_waivers_respect_configured_policy_after_gates(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["full", "partial"],
        "max_partial_percentage": "50",
    }
    full = _governed_compute_evaluation()
    record_ai_fee_decision(full, waiver_type="full", reason="Strategic fit")
    finalize_assessment_fee(full)
    full.refresh_from_db()
    assert full.final_assessment_fee == Decimal("0")
    assert full.final_authority == "ai"

    partial = _governed_compute_evaluation()
    record_ai_fee_decision(
        partial,
        waiver_type="partial",
        reason="Scoped reduction",
        percentage=Decimal("25"),
    )
    finalize_assessment_fee(partial)
    partial.refresh_from_db()
    assert partial.final_assessment_fee == Decimal("750")
    assert partial.customer_fee_status == "partially_waived"


def test_iwl_override_becomes_final_authority_after_substantive_gates():
    ev = _governed_compute_evaluation()
    record_ai_fee_decision(ev, waiver_type="none", reason="Standard fee")
    record_iwl_override(
        ev,
        waiver_type="full",
        reason="IWL strategic exception",
        final_fee=Decimal("0"),
    )
    finalize_assessment_fee(ev)
    ev.refresh_from_db()
    assert ev.iwl_override_applied is True
    assert ev.final_authority == "iwl"
    assert ev.final_assessment_fee == Decimal("0")


def test_non_admin_cannot_override_or_finalize_iwl_fee():
    lead = LeadFactory()
    ev = Evaluation.objects.create(lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE)
    api = APIClient()
    user = UserFactory()
    _login(api, user)
    override = api.post(
        f"/api/v1/evaluations/{ev.id}/iwl-override/",
        {"waiver_type": "full", "reason": "not authorized", "final_fee": "0"},
        format="json",
    )
    finalize = api.post(f"/api/v1/evaluations/{ev.id}/finalize-fee/", {}, format="json")
    assert override.status_code == 403
    assert finalize.status_code == 403


def test_astop_api_rejects_stage_skip_instead_of_directly_assigning_stage(api_client):
    lead = _verified_lead()
    user = AdminUserFactory()
    _login(api_client, user)
    response = api_client.post(
        f"/api/v1/leads/{lead.id}/astop/",
        {
            "stage": "controlled_evaluation",
            "evaluation_agreement": "Agreement",
            "evaluation_scope": _evaluation_scope(),
        },
        format="json",
    )
    assert response.status_code == 400
    assert "sequential_astop_transition_required" in str(response.json())
    record = ASTOPEngagement.objects.filter(lead=lead).first()
    assert record is None


def test_alpha_core_gate_stays_closed_without_validated_software_hardware_case():
    lead = LeadFactory()
    ev = Evaluation.objects.create(lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE)
    decision = alpha_core_gate(ev)
    assert decision.allowed is False
    assert "validated_software_proof_required" in decision.reasons
    assert "incremental_hardware_value_required" in decision.reasons
