"""Focused ALPHA Core opportunity-opening regressions."""
import pytest
from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationPackage
from apps.evaluations.services.alpha_core_opportunity import open_alpha_core_opportunity
from apps.leads.models import ASTOPEngagement, ASTOPStage, CommercialStage, LeadActivity, TrustStatus
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db


def _eligible_compute():
    now = timezone.now()
    lead = LeadFactory(
        sponsor="Executive sponsor",
        trust_status=TrustStatus.PASS,
        trust_screening={"protection_acceptance": True},
        commercial_progress={"economic_relevance": "material", "seriousness": "qualified"},
    )
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
    return Evaluation.objects.create(
        lead=lead,
        lead_name="Buyer",
        company=lead.company,
        pkg=EvaluationPackage.COMPUTE,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
        proof_status="validated",
        hardware_value_case=True,
        hardware_target="Target accelerator platform",
        hardware_economics="Incremental hardware value documented in the governed assessment.",
        hardware_sponsor="Hardware programme sponsor",
        scope="Validated software proof scope",
    )


def test_core_opportunity_opens_only_after_existing_gate_passes():
    source = _eligible_compute()

    result = open_alpha_core_opportunity(source)

    assert result.created is True
    assert result.opportunity.pkg == EvaluationPackage.CORE
    assert result.opportunity.lead_id == source.lead_id
    source.lead.refresh_from_db()
    assert source.lead.current_marketing_stage == CommercialStage.ALPHA_CORE
    assert source.lead.commercial_progress["alpha_core_gate"] is True
    assert source.lead.commercial_progress["alpha_core_opportunity_id"] == str(result.opportunity.id)



def test_core_opportunity_fails_closed_when_compute_substantive_gate_is_not_satisfied():
    source = _eligible_compute()
    source.separate_workload = ""
    source.save(update_fields=["separate_workload", "updated_at"])

    with pytest.raises(ValueError, match="alpha_compute_gate:.*separate_workload_required"):
        open_alpha_core_opportunity(source)

    assert Evaluation.objects.filter(lead=source.lead, pkg=EvaluationPackage.CORE).count() == 0

def test_core_opportunity_fails_closed_without_required_hardware_case():
    source = _eligible_compute()
    source.hardware_value_case = False
    source.hardware_target = ""
    source.hardware_economics = ""
    source.hardware_sponsor = ""
    source.save(
        update_fields=[
            "hardware_value_case", "hardware_target", "hardware_economics", "hardware_sponsor", "updated_at"
        ]
    )

    with pytest.raises(ValueError) as exc:
        open_alpha_core_opportunity(source)

    text = str(exc.value)
    assert "incremental_hardware_value_required" in text
    assert "hardware_target_required" in text
    assert "hardware_economics_required" in text
    assert "hardware_sponsor_required" in text
    assert Evaluation.objects.filter(lead=source.lead, pkg=EvaluationPackage.CORE).count() == 0


def test_core_opportunity_does_not_open_from_core_or_unvalidated_source():
    source = _eligible_compute()
    source.proof_status = "pending"
    source.save(update_fields=["proof_status", "updated_at"])

    with pytest.raises(ValueError, match="validated_software_proof_required"):
        open_alpha_core_opportunity(source)

    core = Evaluation.objects.create(
        lead=LeadFactory(),
        pkg=EvaluationPackage.CORE,
        proof_status="validated",
        hardware_value_case=True,
        hardware_target="target",
        hardware_economics="economics",
        hardware_sponsor="sponsor",
    )
    with pytest.raises(ValueError, match="validated_software_proof_required"):
        open_alpha_core_opportunity(core)


def test_core_opportunity_opening_is_idempotent():
    source = _eligible_compute()

    first = open_alpha_core_opportunity(source)
    second = open_alpha_core_opportunity(source)

    assert first.created is True
    assert second.created is False
    assert first.opportunity.id == second.opportunity.id
    assert Evaluation.objects.filter(lead=source.lead, pkg=EvaluationPackage.CORE).count() == 1
    assert LeadActivity.objects.filter(lead=source.lead, meta__domain="alpha_core_opportunity").count() == 1


def test_core_opportunity_copies_only_existing_governed_hardware_case_facts():
    source = _eligible_compute()
    result = open_alpha_core_opportunity(source)

    opportunity = result.opportunity
    assert opportunity.hardware_value_case is True
    assert opportunity.hardware_target == source.hardware_target
    assert opportunity.hardware_economics == source.hardware_economics
    assert opportunity.hardware_sponsor == source.hardware_sponsor
    assert opportunity.scope == source.scope


def test_core_opportunity_endpoint_is_internal_write_and_viewer_is_blocked(api_client):
    source = _eligible_compute()
    url = f"/api/v1/evaluations/{source.id}/alpha-core-opportunity/"

    anonymous = api_client.post(url, {}, format="json")
    assert anonymous.status_code in {401, 403}

    api_client.force_authenticate(user=ViewerUserFactory())
    assert api_client.post(url, {}, format="json").status_code == 403

    api_client.force_authenticate(user=AdminUserFactory())
    response = api_client.post(url, {}, format="json")
    assert response.status_code == 201
    assert response.json()["created"] is True
    assert response.json()["opportunity"]["pkg"] == EvaluationPackage.CORE
