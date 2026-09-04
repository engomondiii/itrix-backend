"""Focused September-2026 ASTOP → ALPHA commercial-governance regressions."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.leads.models import ASTOPEngagement, ASTOPStage
from apps.leads.services.commercial_progression import (
    alpha_compute_gate,
    alpha_core_gate,
    finalize_assessment_fee,
    record_ai_fee_decision,
    record_iwl_override,
)
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


def _qualified_astop(lead, *, verified=False):
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.VERIFY_EXPAND if verified else ASTOPStage.LO_DEPLOYMENT,
        lo_executed_at=None,
        verified_value={"annual_value": "100"} if verified else {},
    )
    return record


def test_lo_commercial_stage_can_exist_before_execution_but_production_cannot(api_client):
    lead = LeadFactory()
    user = AdminUserFactory()
    _login(api_client, user)

    ok = api_client.post(
        f"/api/v1/leads/{lead.id}/astop/",
        {"stage": "lo_deployment", "lo_scope": {"field": "agent-observation"}},
        format="json",
    )
    assert ok.status_code == 200

    blocked = api_client.post(
        f"/api/v1/leads/{lead.id}/astop/",
        {"stage": "verify_expand", "verified_value": {"annual_value": "100"}},
        format="json",
    )
    assert blocked.status_code == 400
    assert "executed License-Out" in str(blocked.json())


def test_alpha_compute_gate_requires_verified_astop_and_separate_workload():
    lead = LeadFactory(sponsor="Executive sponsor", commercial_progress={"economic_relevance": "material"})
    _qualified_astop(lead, verified=False)
    decision = alpha_compute_gate(lead, separate_workload="", technical_route="axiom_tensor")
    assert decision.allowed is False
    assert "astop_verified_value_required" in decision.reasons
    assert "separate_workload_required" in decision.reasons


def test_alpha_assessment_is_paid_by_default_and_ai_no_waiver_is_final_authority(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {}
    lead = LeadFactory()
    ev = Evaluation.objects.create(
        lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE, standard_assessment_fee=Decimal("1000")
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


def test_ai_full_and_partial_waivers_respect_configured_policy(settings):
    settings.ALPHA_ASSESSMENT_FEE_POLICY = {
        "enabled": True,
        "allowed_waiver_types": ["full", "partial"],
        "max_partial_percentage": "50",
    }
    lead = LeadFactory()
    full = Evaluation.objects.create(
        lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE, standard_assessment_fee=Decimal("1000")
    )
    record_ai_fee_decision(full, waiver_type="full", reason="Strategic fit")
    finalize_assessment_fee(full)
    full.refresh_from_db()
    assert full.final_assessment_fee == Decimal("0")
    assert full.final_authority == "ai"

    partial = Evaluation.objects.create(
        lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE, standard_assessment_fee=Decimal("1000")
    )
    record_ai_fee_decision(partial, waiver_type="partial", reason="Scoped reduction", percentage=Decimal("25"))
    finalize_assessment_fee(partial)
    partial.refresh_from_db()
    assert partial.final_assessment_fee == Decimal("750")
    assert partial.customer_fee_status == "partially_waived"


def test_iwl_override_becomes_final_authority():
    lead = LeadFactory()
    ev = Evaluation.objects.create(
        lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE, standard_assessment_fee=Decimal("1000")
    )
    record_ai_fee_decision(ev, waiver_type="none", reason="Standard fee")
    record_iwl_override(ev, waiver_type="full", reason="IWL strategic exception", final_fee=Decimal("0"))
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


def test_alpha_core_gate_stays_closed_without_validated_software_hardware_case():
    lead = LeadFactory()
    ev = Evaluation.objects.create(lead=lead, lead_name="Buyer", pkg=EvaluationPackage.COMPUTE)
    decision = alpha_core_gate(ev)
    assert decision.allowed is False
    assert "validated_software_proof_required" in decision.reasons
    assert "incremental_hardware_value_required" in decision.reasons
