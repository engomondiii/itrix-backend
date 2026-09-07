"""Focused truthful ASTOP production-readiness regressions."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, ASTOPStage, TrustStatus
from apps.leads.services.entitlement_lifecycle import update_astop_entitlement
from apps.leads.services.readiness import (
    READINESS_KEYS,
    current_readiness,
    overall_readiness_state,
    readiness_gate,
    set_astop_readiness,
)
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, UserFactory

pytestmark = pytest.mark.django_db


def _lead_record():
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
        organization="Acme Corp",
        identity_verified_at=now,
        organization_verified_at=now,
        nda_signed=True,
        nda_signed_at=now,
    )
    terms = {
        "rights": {
            "rights_type": "None",
            "licensed_party": "Acme Corp",
            "business_unit": "Observation platform",
            "field_of_use": "agent observation",
            "environments": ["production"],
            "redistribution": "not authorized",
            "audit_terms": "contract-defined audit terms",
        },
        "economics": {"support_security_upgrades": "as executed"},
        "status": "final",
        "provenance": {"source_reference": "executed LO"},
    }
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
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
        measured_savings={"value": 0, "provenance": "controlled measurement"},
        estimated_savings={"value": None, "provenance": "not estimated"},
        evaluation_result={"status": "passed", "reproducible": True},
        security_result={"status": "passed"},
        integration_feasibility={"status": "passed"},
        lo_scope={"field_of_use": "agent observation", "governed_terms": terms},
        lo_executed_at=now,
        controlled_build_id="build-verified",
        attribution_id="attr-verified",
    )
    return lead, record


def _all_ready():
    return {key: {"status": "READY", "reference": f"evidence:{key}"} for key in READINESS_KEYS}


def test_missing_readiness_is_truthfully_not_provided_and_fails_closed():
    _lead, record = _lead_record()
    assert overall_readiness_state(record) == "NOT_PROVIDED"
    assert all(row["status"] == "NOT_PROVIDED" for row in current_readiness(record).values())
    reasons = readiness_gate(record)
    assert "readiness_threat_model_not_provided" in reasons
    assert "readiness_deployment_package_not_provided" in reasons


def test_admin_can_record_all_ready_without_fabricating_external_completion():
    lead, record = _lead_record()
    result = set_astop_readiness(lead, updates=_all_ready(), by=AdminUserFactory())
    record.refresh_from_db()
    assert result.changed is True
    assert overall_readiness_state(record) == "READY"
    assert readiness_gate(record) == ()


def test_blocked_or_failed_readiness_blocks_production_activation():
    lead, record = _lead_record()
    updates = _all_ready()
    updates["security_review"] = {"status": "BLOCKED", "reference": "security review pending fix"}
    set_astop_readiness(lead, updates=updates, by=AdminUserFactory())
    with pytest.raises(ValueError, match="readiness_security_review_blocked"):
        update_astop_entitlement(lead, action="activate")


def test_production_activation_succeeds_only_after_every_required_readiness_gate_passes():
    lead, record = _lead_record()
    set_astop_readiness(lead, updates=_all_ready(), by=AdminUserFactory())
    result = update_astop_entitlement(lead, action="activate")
    record.refresh_from_db()
    assert result.changed is True
    assert record.entitlement_status == "active"


def test_non_admin_cannot_mutate_readiness():
    lead, _ = _lead_record()
    with pytest.raises(PermissionError, match="admin_required"):
        set_astop_readiness(lead, updates={"security_review": {"status": "READY"}}, by=UserFactory())


def test_readiness_endpoint_is_team_read_admin_write(api_client):
    lead, _ = _lead_record()
    url = f"/api/v1/leads/{lead.id}/astop-readiness/"

    api_client.force_authenticate(user=UserFactory())
    assert api_client.get(url).status_code == 200
    assert api_client.post(url, {"readiness": {"security_review": {"status": "READY"}}}, format="json").status_code == 403

    api_client.force_authenticate(user=AdminUserFactory())
    response = api_client.post(
        url,
        {"readiness": {"security_review": {"status": "IN_REVIEW", "reference": "review-123"}}},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["readiness"]["security_review"]["status"] == "IN_REVIEW"


def test_identical_readiness_update_is_idempotent():
    lead, _ = _lead_record()
    admin = AdminUserFactory()
    first = set_astop_readiness(lead, updates={"security_review": {"status": "READY", "reference": "sec-1"}}, by=admin)
    second = set_astop_readiness(lead, updates={"security_review": {"status": "READY", "reference": "sec-1"}}, by=admin)
    assert first.changed is True
    assert second.changed is False
