"""Focused cross-product ASTOP → ALPHA Compute → ALPHA Core state regressions."""
from __future__ import annotations

from django.utils import timezone
import pytest

from apps.analytics.services import management_reporting
from apps.customer_success.services.astop_integration import snapshot
from apps.evaluations.models import Evaluation, EvaluationPackage, EvaluationStatus, WaiverType
from apps.evaluations.services.alpha_core_opportunity import open_alpha_core_opportunity
from apps.leads.models import ASTOPEngagement, ASTOPStage, CommercialStage, Lead, LeadActivity, TrustStatus
from apps.leads.services.commercial_progression import record_ai_fee_decision
from apps.leads.services.lead_updater import apply_acquisition_context
from apps.leads.services.progression_state import (
    customer_safe_progression_state,
    derive_progression_state,
    sync_progression_state,
)
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def _governed_lead():
    now = timezone.now()
    lead = LeadFactory(
        business_unit="Observation platform",
        sponsor="Executive sponsor",
        compute_bottleneck="Decision-time observation cost",
        workload_type="Agent observation workflow",
        trust_status=TrustStatus.PASS,
        trust_screening={"protection_acceptance": True},
        commercial_progress={
            "economic_relevance": "material",
            "seriousness": "qualified",
        },
    )
    client = ClientFactory(
        lead=lead,
        identity_verified_at=now,
        organization_verified_at=now,
        nda_signed=True,
        nda_signed_at=now,
    )
    return lead, client


def _astop(lead):
    now = timezone.now()
    return ASTOPEngagement.objects.create(
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
            "observation_behavior": "Observe decision-time token/tool usage",
            "model_or_controller": "Controlled controller A",
            "workflow": "Agent observation workflow",
        },
        baseline={"measurement_window": "versioned controlled baseline window"},
        decision_fidelity={"status": "passed"},
        measured_savings={"value": 0, "provenance": "controlled measurement"},
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


def _compute(lead):
    return Evaluation.objects.create(
        lead=lead,
        lead_name=lead.company or lead.visitor_name or "Lead",
        company=lead.company or "",
        pkg=EvaluationPackage.COMPUTE,
        status=EvaluationStatus.PROPOSED,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
    )


def _core_ready(compute):
    compute.proof_status = "validated"
    compute.hardware_value_case = True
    compute.hardware_target = "Target accelerator architecture"
    compute.hardware_economics = "Bounded incremental hardware value case"
    compute.hardware_sponsor = "Executive sponsor"
    compute.save(
        update_fields=[
            "proof_status",
            "hardware_value_case",
            "hardware_target",
            "hardware_economics",
            "hardware_sponsor",
            "updated_at",
        ]
    )
    return compute


def test_astop_verified_gate_persists_from_actual_proof_state():
    lead, _client = _governed_lead()
    _astop(lead)

    lead.refresh_from_db()
    state = derive_progression_state(lead)

    assert state.astop_verified_value_gate is True
    assert lead.commercial_progress["astop_verified_value_gate"] is True
    assert lead.current_marketing_stage == CommercialStage.ASTOP


def test_alpha_compute_gate_persists_only_when_substantive_gate_passes():
    lead, _client = _governed_lead()
    _astop(lead)
    _compute(lead)

    lead.refresh_from_db()

    assert lead.commercial_progress["alpha_compute_gate"] is True
    assert lead.current_marketing_stage == CommercialStage.ALPHA_COMPUTE


def test_alpha_core_gate_persists_from_validated_compute_and_hardware_case():
    lead, _client = _governed_lead()
    _astop(lead)
    compute = _core_ready(_compute(lead))

    lead.refresh_from_db()

    assert derive_progression_state(lead).alpha_core_gate is True
    assert lead.commercial_progress["alpha_core_gate"] is True
    assert lead.commercial_progress["next_best_action"] == "open_alpha_core_opportunity"


def test_next_best_action_tracks_actual_gate_and_opportunity_state():
    lead, _client = _governed_lead()
    _astop(lead)
    lead.refresh_from_db()
    assert lead.commercial_progress["next_best_action"] == "open_alpha_compute_assessment"

    compute = _compute(lead)
    lead.refresh_from_db()
    assert lead.commercial_progress["next_best_action"] == "complete_alpha_core_case"

    _core_ready(compute)
    lead.refresh_from_db()
    assert lead.commercial_progress["next_best_action"] == "open_alpha_core_opportunity"

    result = open_alpha_core_opportunity(compute, by=AdminUserFactory())
    lead.refresh_from_db()
    assert result.created is True
    assert lead.current_marketing_stage == CommercialStage.ALPHA_CORE
    assert lead.commercial_progress["next_best_action"] == "progress_alpha_core_opportunity"


def test_fee_waiver_does_not_promote_marketing_or_product_stage(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {"enabled": False}
    lead = LeadFactory(current_marketing_stage=CommercialStage.DISCOVERY)
    evaluation = Evaluation.objects.create(
        lead=lead,
        pkg=EvaluationPackage.COMPUTE,
        separate_workload="Interest-only record",
        technical_route="axiom_tensor",
    )
    lead.refresh_from_db()
    assert lead.current_marketing_stage == CommercialStage.DISCOVERY

    record_ai_fee_decision(
        evaluation,
        waiver_type=WaiverType.NONE,
        reason="No delegated waiver applies.",
    )
    lead.refresh_from_db()

    assert lead.current_marketing_stage == CommercialStage.DISCOVERY


def test_trusted_introduction_does_not_promote_product_stage():
    lead = LeadFactory(current_marketing_stage=CommercialStage.DISCOVERY)

    apply_acquisition_context(
        lead,
        context={
            "source_channel": "partner",
            "trusted_introduction_confirmed": True,
        },
        by=AdminUserFactory(),
    )
    lead.refresh_from_db()

    assert lead.current_marketing_stage == CommercialStage.DISCOVERY
    assert not bool((lead.commercial_progress or {}).get("alpha_compute_gate"))
    assert not bool((lead.commercial_progress or {}).get("alpha_core_gate"))


def test_repeated_gate_state_synchronization_is_idempotent_and_audited_once():
    lead, _client = _governed_lead()
    _astop(lead)
    Lead.objects.filter(pk=lead.pk).update(
        current_marketing_stage=CommercialStage.DISCOVERY,
        commercial_progress={"next_best_action": "stale_frontend_guess"},
    )
    lead.refresh_from_db()

    _state, first_changed = sync_progression_state(lead, audit=True)
    lead.refresh_from_db()
    _state, second_changed = sync_progression_state(lead, audit=True)

    assert first_changed is True
    assert second_changed is False
    assert LeadActivity.objects.filter(
        lead=lead, meta__domain="cross_product_progression"
    ).count() == 1


def test_customer_safe_progression_hides_iwl_override_and_protected_rationale():
    lead, _client = _governed_lead()
    _astop(lead)
    evaluation = _compute(lead)
    evaluation.iwl_override_applied = True
    evaluation.iwl_override_status = "partial"
    evaluation.iwl_override_reason = "protected internal deliberation"
    evaluation.final_authority = "iwl"
    evaluation.save(
        update_fields=[
            "iwl_override_applied",
            "iwl_override_status",
            "iwl_override_reason",
            "final_authority",
            "updated_at",
        ]
    )

    safe = customer_safe_progression_state(lead)
    serialized = str(safe).lower()

    assert "iwl" not in serialized
    assert "protected internal deliberation" not in serialized
    assert "reason" not in serialized


def test_core_opportunity_opening_and_state_recalculation_are_idempotent():
    lead, _client = _governed_lead()
    _astop(lead)
    compute = _core_ready(_compute(lead))
    actor = AdminUserFactory()

    first = open_alpha_core_opportunity(compute, by=actor)
    second = open_alpha_core_opportunity(compute, by=actor)

    assert first.created is True
    assert second.created is False
    assert second.opportunity.id == first.opportunity.id
    assert Evaluation.objects.filter(lead=lead, pkg=EvaluationPackage.CORE).count() == 1
    lead.refresh_from_db()
    assert lead.commercial_progress["alpha_core_gate"] is True
    assert lead.commercial_progress["next_best_action"] == "progress_alpha_core_opportunity"


def test_analytics_and_customer_success_consume_same_governed_progression_state():
    lead, client = _governed_lead()
    client.first_payment_recorded_at = timezone.now()
    client.save(update_fields=["first_payment_recorded_at", "updated_at"])
    _astop(lead)
    compute = _core_ready(_compute(lead))
    open_alpha_core_opportunity(compute, by=AdminUserFactory())
    lead.refresh_from_db()

    customer = snapshot(client)["governedProgression"]
    analytics = management_reporting.summary()["progression"]

    assert customer["currentMarketingStage"] == lead.current_marketing_stage
    assert customer["nextBestAction"] == lead.commercial_progress["next_best_action"]
    assert customer["alphaCoreReady"] is True
    assert analytics["alphaCoreGatePass"] == 1
    assert analytics["byNextBestAction"]["progress_alpha_core_opportunity"] == 1
