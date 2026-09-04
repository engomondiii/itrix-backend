"""Focused ASTOP License-Out entitlement lifecycle regressions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.leads.models import ASTOPEngagement, ASTOPStage, LeadActivity, TrustStatus
from apps.leads.serializers import ASTOPProgressSerializer
from apps.leads.services.commercial_progression import alpha_compute_gate
from apps.leads.services.entitlement_lifecycle import (
    entitlement_lifecycle_state,
    update_astop_entitlement,
)
from apps.leads.services.readiness import READINESS_KEYS
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db


def _verified_lead():
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
    now = timezone.now()
    ClientFactory(
        lead=lead,
        identity_verified_at=now,
        organization_verified_at=now,
        nda_signed=True,
        nda_signed_at=now,
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


def _proof_values():
    return {
        "baseline": {"measurement_window": "versioned controlled baseline window"},
        "decision_fidelity": {"status": "passed"},
        "measured_savings": {"value": 0, "provenance": "controlled measurement"},
        "estimated_savings": {"value": None, "provenance": "not estimated"},
        "evaluation_result": {"status": "passed", "reproducible": True},
        "security_result": {"status": "passed"},
        "integration_feasibility": {"status": "passed"},
    }


def _governed_terms():
    return {
        "rights": {
            "rights_type": "None",
            "licensed_party": "Acme Corp",
            "business_unit": "Observation platform",
            "field_of_use": "agent observation",
            "environments": ["production"],
            "redistribution": "not authorized",
            "audit_terms": "contract-defined audit terms",
        },
        "economics": {"support_security_upgrades": "as executed in the License-Out"},
        "status": "final",
        "provenance": {"source_reference": "executed License-Out"},
    }


def _release_readiness():
    return {key: {"status": "READY"} for key in READINESS_KEYS}


def _lo_record(*, stage=ASTOPStage.LO_DEPLOYMENT, entitlement_status=""):
    lead = _verified_lead()
    record = ASTOPEngagement.objects.create(
        lead=lead,
        stage=stage,
        qualification_context=_qualification_context(),
        evaluation_agreement="Controlled evaluation agreement",
        evaluation_scope=_evaluation_scope(),
        lo_scope={
            "field_of_use": "agent observation",
            "governed_terms": _governed_terms(),
            "release_readiness": _release_readiness(),
        },
        lo_executed_at=timezone.now(),
        entitlement_status=entitlement_status,
        controlled_build_id="build-verified",
        attribution_id="attr-verified",
        **_proof_values(),
    )
    return lead, record


def _verified_record():
    lead, record = _lo_record(stage=ASTOPStage.VERIFY_EXPAND, entitlement_status="active")
    record.verified_value = {"status": "verified", "basis": "controlled proof"}
    record.save(update_fields=["verified_value", "updated_at"])
    return lead, record


def test_activation_requires_governed_production_prerequisites():
    lead = _verified_lead()
    ASTOPEngagement.objects.create(
        lead=lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
        lo_executed_at=timezone.now(),
        lo_scope={"field_of_use": "agent observation"},
    )

    with pytest.raises(ValueError) as exc:
        update_astop_entitlement(lead, action="activate")

    text = str(exc.value)
    assert "controlled_build_required" in text
    assert "attribution_required" in text
    assert "evaluation_agreement_required" in text
    assert "governed_terms_required" in text
    assert "readiness_threat_model_not_provided" in text


def test_pending_entitlement_can_activate_when_all_gates_pass():
    lead, record = _lo_record()
    expires_at = timezone.now() + timedelta(days=30)

    result = update_astop_entitlement(
        lead,
        action="activate",
        expires_at=expires_at,
        reason="Executed License-Out activated",
    )

    record.refresh_from_db()
    assert result.changed is True
    assert record.entitlement_status == "active"
    assert record.entitlement_expires_at == expires_at
    assert entitlement_lifecycle_state(record) == "active"


def test_expiry_state_is_derived_from_actual_timestamp():
    _, record = _lo_record(entitlement_status="active")
    record.entitlement_expires_at = timezone.now() - timedelta(seconds=1)
    record.save(update_fields=["entitlement_expires_at", "updated_at"])

    assert entitlement_lifecycle_state(record) == "expired"


def test_expire_transition_is_terminal_and_idempotent():
    lead, record = _lo_record(entitlement_status="active")

    first = update_astop_entitlement(lead, action="expire", reason="Term completed")
    second = update_astop_entitlement(lead, action="expire", reason="Repeated request")

    record.refresh_from_db()
    assert first.changed is True
    assert second.changed is False
    assert record.entitlement_status == "expired"
    assert record.entitlement_expires_at is not None
    with pytest.raises(ValueError, match="expired_entitlement_cannot_activate"):
        update_astop_entitlement(lead, action="activate")


def test_revocation_is_terminal_audited_and_idempotent():
    lead, record = _lo_record(entitlement_status="active")

    first = update_astop_entitlement(lead, action="revoke", reason="Governed revocation")
    second = update_astop_entitlement(lead, action="revoke", reason="Repeated request")

    record.refresh_from_db()
    assert first.changed is True
    assert second.changed is False
    assert record.entitlement_status == "revoked"
    assert record.revocation_status == "revoked"
    assert entitlement_lifecycle_state(record) == "revoked"
    activities = LeadActivity.objects.filter(
        lead=lead,
        type=LeadActivity.ActivityType.STATUS_CHANGE,
        meta__domain="astop_entitlement",
    )
    assert activities.count() == 1
    with pytest.raises(ValueError, match="revoked_entitlement_cannot_activate"):
        update_astop_entitlement(lead, action="activate")


def test_revoked_entitlement_blocks_alpha_compute_progression():
    lead, _record = _verified_record()
    update_astop_entitlement(lead, action="revoke", reason="Access withdrawn")

    decision = alpha_compute_gate(
        lead,
        separate_workload="Separate tensor workload",
        technical_route="axiom_tensor",
    )

    assert decision.allowed is False
    assert "active_entitlement_required" in decision.reasons
    assert "entitlement_revoked_or_suspended" in decision.reasons


def test_generic_astop_progress_cannot_write_terminal_entitlement_states():
    for terminal in ("expired", "revoked", "suspended", "blocked"):
        serializer = ASTOPProgressSerializer(
            data={"stage": "lo_deployment", "entitlement_status": terminal}
        )
        assert serializer.is_valid() is False
        assert "entitlement_status" in serializer.errors


def test_entitlement_endpoint_is_team_only_and_viewer_cannot_mutate(api_client):
    lead, record = _lo_record(entitlement_status="active")
    url = f"/api/v1/leads/{lead.id}/astop-entitlement/"

    anonymous = api_client.get(url)
    assert anonymous.status_code in {401, 403}

    viewer = ViewerUserFactory()
    api_client.force_authenticate(user=viewer)
    readable = api_client.get(url)
    blocked_write = api_client.post(url, {"action": "revoke", "reason": "x"}, format="json")
    assert readable.status_code == 200
    assert blocked_write.status_code == 403

    admin = AdminUserFactory()
    api_client.force_authenticate(user=admin)
    response = api_client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert body["entitlementLifecycleState"] == "active"
    assert body["entitlementStatus"] == record.entitlement_status
    assert "revocationStatus" in body
    assert "entitlementExpiresAt" in body


def test_entitlement_endpoint_mutation_returns_truthful_lifecycle_state(api_client):
    lead, _record = _lo_record(entitlement_status="active")
    api_client.force_authenticate(user=AdminUserFactory())

    response = api_client.post(
        f"/api/v1/leads/{lead.id}/astop-entitlement/",
        {"action": "revoke", "reason": "Governed withdrawal"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert response.json()["entitlementLifecycleState"] == "revoked"
