"""Focused governed ASTOP License-Out terms regressions."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.clients.serializers import PortalEvaluationSerializer
from apps.core.exceptions import ResourceConflict
from apps.leads.models import ASTOPEngagement, ASTOPStage, LeadActivity, TrustStatus
from apps.leads.services.entitlement_lifecycle import update_astop_entitlement
from apps.leads.services.lo_terms import customer_safe_lo_summary, set_governed_lo_terms
from apps.leads.services.readiness import READINESS_KEYS
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, UserFactory

pytestmark = pytest.mark.django_db


def _lead_and_record():
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
            "environment": "production",
        },
        baseline={"measurement_window": "versioned controlled baseline window"},
        decision_fidelity={"status": "passed"},
        measured_savings={"value": 0, "provenance": "controlled measurement"},
        estimated_savings={"value": None, "provenance": "not estimated"},
        evaluation_result={"status": "passed", "reproducible": True},
        security_result={"status": "passed"},
        integration_feasibility={"status": "passed"},
        lo_scope={
            "field_of_use": "agent observation",
            "environment": "production",
            "release_readiness": {key: {"status": "READY"} for key in READINESS_KEYS},
        },
        controlled_build_id="build-verified",
        attribution_id="attr-verified",
    )
    return lead, record


def _rights(**overrides):
    value = {
        "rights_type": "None",
        "licensed_party": "Acme Corp",
        "business_unit": "Observation platform",
        "field_of_use": "agent observation",
        "environments": ["production"],
        "redistribution": "not authorized",
        "audit_terms": "contract-defined audit terms",
    }
    value.update(overrides)
    return value


def _economics(**overrides):
    value = {"support_security_upgrades": "as agreed in the License-Out"}
    value.update(overrides)
    return value


def _set_final(lead, *, by=None, rights=None, economics=None):
    return set_governed_lo_terms(
        lead,
        rights=rights or _rights(),
        economics=economics or _economics(),
        status="final",
        source_reference="approved order form",
        by=by or AdminUserFactory(),
    )


def test_admin_can_create_governed_terms_with_provenance():
    lead, record = _lead_and_record()
    admin = AdminUserFactory()
    result = _set_final(lead, by=admin)

    record.refresh_from_db()
    terms = record.lo_scope["governed_terms"]
    assert result.changed is True
    assert terms["rights"]["rights_type"] == "None"
    assert terms["status"] == "final"
    assert terms["provenance"]["setter_id"] == str(admin.id)
    assert terms["provenance"]["recorded_at"]
    assert terms["provenance"]["source_reference"] == "approved order form"
    assert LeadActivity.objects.filter(lead=lead, meta__domain="astop_lo_terms").count() == 1


def test_non_admin_service_cannot_mutate_governed_terms():
    lead, _ = _lead_and_record()
    with pytest.raises(PermissionError, match="admin_required"):
        _set_final(lead, by=UserFactory())


def test_team_endpoint_blocks_non_admin_and_customer_plane_credentials(api_client):
    lead, _ = _lead_and_record()
    url = f"/api/v1/leads/{lead.id}/astop-lo-terms/"
    payload = {
        "rights": _rights(),
        "economics": _economics(),
        "status": "final",
        "source_reference": "approved order form",
    }

    api_client.force_authenticate(user=UserFactory())
    assert api_client.post(url, payload, format="json").status_code == 403

    api_client.force_authenticate(user=lead.client_account)
    assert api_client.post(url, payload, format="json").status_code in {401, 403}

    api_client.force_authenticate(user=AdminUserFactory())
    assert api_client.post(url, payload, format="json").status_code == 200


def test_governed_terms_require_non_empty_rights_and_economics():
    lead, _ = _lead_and_record()
    admin = AdminUserFactory()
    with pytest.raises(ValueError, match="governed_rights_required"):
        set_governed_lo_terms(lead, rights={}, economics=_economics(), status="final", by=admin)
    with pytest.raises(ValueError, match="governed_economics_required"):
        set_governed_lo_terms(lead, rights=_rights(), economics={}, status="final", by=admin)


def test_governed_terms_do_not_inject_fixed_astop_pricing():
    lead, record = _lead_and_record()
    submitted = {"support_security_upgrades": "subject to the executed order form"}
    _set_final(lead, economics=submitted)
    record.refresh_from_db()
    assert record.lo_scope["governed_terms"]["economics"] == submitted


def test_lo_execution_requires_final_governed_terms_and_scope():
    _, record = _lead_and_record()
    record.lo_executed_at = timezone.now()

    with pytest.raises(ResourceConflict, match="final governed terms"):
        record.save(update_fields=["lo_executed_at", "updated_at"])

    record.refresh_from_db()
    assert record.lo_executed_at is None


def test_entitlement_activation_fails_for_legacy_executed_row_without_governed_terms():
    lead, record = _lead_and_record()
    # Historical-state setup deliberately bypasses model signals: lifecycle activation
    # must still fail closed when an old executed row has no governed terms snapshot.
    ASTOPEngagement.objects.filter(pk=record.pk).update(lo_executed_at=timezone.now())
    with pytest.raises(ValueError, match="governed_terms_required"):
        update_astop_entitlement(lead, action="activate")


def test_entitlement_activation_succeeds_with_executed_final_terms_and_other_gates():
    lead, record = _lead_and_record()
    _set_final(lead)
    record.refresh_from_db()
    record.lo_executed_at = timezone.now()
    record.save(update_fields=["lo_executed_at", "updated_at"])

    result = update_astop_entitlement(lead, action="activate")
    record.refresh_from_db()
    assert result.changed is True
    assert record.entitlement_status == "active"


def test_executed_snapshot_cannot_be_silently_overwritten():
    lead, record = _lead_and_record()
    admin = AdminUserFactory()
    _set_final(lead, by=admin)
    record.refresh_from_db()
    record.lo_executed_at = timezone.now()
    record.save(update_fields=["lo_executed_at", "updated_at"])

    with pytest.raises(ValueError, match="executed_lo_governed_terms_immutable"):
        _set_final(lead, by=admin, rights=_rights(field_of_use="another field"))


def test_executed_lo_timestamp_cannot_be_cleared_or_rewritten():
    lead, record = _lead_and_record()
    _set_final(lead)
    record.refresh_from_db()
    executed_at = timezone.now()
    record.lo_executed_at = executed_at
    record.save(update_fields=["lo_executed_at", "updated_at"])

    record.lo_executed_at = None
    with pytest.raises(ResourceConflict, match="timestamp is immutable"):
        record.save(update_fields=["lo_executed_at", "updated_at"])

    record.refresh_from_db()
    assert record.lo_executed_at == executed_at


def test_identical_internal_write_is_idempotent():
    lead, _ = _lead_and_record()
    admin = AdminUserFactory()
    first = _set_final(lead, by=admin)
    second = _set_final(lead, by=admin)
    assert first.changed is True
    assert second.changed is False
    assert LeadActivity.objects.filter(lead=lead, meta__domain="astop_lo_terms").count() == 1


def test_scope_mismatch_blocks_production_activation():
    lead, record = _lead_and_record()
    _set_final(lead, rights=_rights(field_of_use="bounded field"))
    record.refresh_from_db()
    # Build an intentionally inconsistent historical state without weakening the current
    # execution guard; activation must still re-check the governed scope.
    ASTOPEngagement.objects.filter(pk=record.pk).update(
        lo_executed_at=timezone.now(),
        lo_scope={**record.lo_scope, "field_of_use": "different field"},
    )

    with pytest.raises(ValueError, match="field_of_use_outside_governed_scope"):
        update_astop_entitlement(lead, action="activate")


def test_customer_safe_serializer_hides_economics_provenance_and_audit_terms():
    lead, record = _lead_and_record()
    _set_final(
        lead,
        rights=_rights(audit_terms="internal audit detail"),
        economics={"access_fee": "confidential negotiated amount", "currency": "USD"},
    )
    record.refresh_from_db()
    payload = {
        "exists": True,
        "kind": "astop",
        "stage": record.stage,
        "astopStage": record.stage,
        "kpis": [],
        "reportHref": "",
        **customer_safe_lo_summary(record),
    }
    data = PortalEvaluationSerializer(payload).data
    serialized = str(data).lower()
    assert "economics" not in serialized
    assert "provenance" not in serialized
    assert "audit_terms" not in serialized
    assert "confidential negotiated amount" not in serialized
    assert data["licensedScopeSummary"]["field_of_use"] == "agent observation"
