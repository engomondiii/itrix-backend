"""Focused ASTOP Customer Success integration regressions."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients.tokens import build_tokens_for_client
from apps.customer_success.models import SupportRequest
from apps.customer_success.services.astop_integration import snapshot
from apps.leads.models import ASTOPEngagement, ASTOPStage

pytestmark = pytest.mark.django_db


def _record(client, *, end_offset=90):
    now = timezone.now()
    terms = {
        "rights": {
            "rights_type": "None",
            "licensed_party": client.organization,
            "field_of_use": "agent observation",
            "environments": ["production"],
            "redistribution": "not authorized",
            "audit_terms": "internal audit detail",
        },
        "economics": {"access_fee": "confidential negotiated amount"},
        "status": "final",
        "provenance": {"source_reference": "executed order form", "setter_name": "Internal"},
    }
    return ASTOPEngagement.objects.create(
        lead=client.lead,
        stage=ASTOPStage.VERIFY_EXPAND,
        lo_scope={"field_of_use": "agent observation", "governed_terms": terms},
        lo_executed_at=now,
        entitlement_status="active",
        entitlement_expires_at=now + timedelta(days=30),
        authorized_install_at=now,
        reproducible_value_at=now + timedelta(seconds=end_offset),
        verified_value={"status": "verified", "basis": "controlled proof"},
        expansion={"status": "in_review", "internal_note": "never expose"},
    )


def test_customer_success_snapshot_includes_astop_ttfv_value_lo_entitlement_and_expansion(paying_client):
    _record(paying_client)

    data = snapshot(paying_client)

    assert data["customerSuccessActive"] is True
    assert data["astopStage"] == ASTOPStage.VERIFY_EXPAND
    assert data["ttfvSeconds"] == 90
    assert data["verifiedValue"] is True
    assert data["verifiedValueStatus"] == "verified"
    assert data["loStatus"] == "executed"
    assert data["entitlementState"] == "active"
    assert data["expansionStatus"] == "in_review"
    assert data["deploymentScope"]["field_of_use"] == "agent observation"


def test_customer_success_ttfv_is_null_when_incomplete_or_temporally_invalid(paying_client):
    record = _record(paying_client)
    record.reproducible_value_at = None
    record.save(update_fields=["reproducible_value_at", "updated_at"])
    assert snapshot(paying_client)["ttfvSeconds"] is None

    record.reproducible_value_at = record.authorized_install_at - timedelta(seconds=1)
    record.save(update_fields=["reproducible_value_at", "updated_at"])
    assert snapshot(paying_client)["ttfvSeconds"] is None


def test_blocking_support_is_the_customer_safe_next_action(paying_client):
    _record(paying_client)
    SupportRequest.objects.create(
        client=paying_client,
        subject="Production blocked",
        body="Cannot proceed",
        blocking=True,
        status=SupportRequest.Status.OPEN,
    )

    data = snapshot(paying_client)

    assert data["support"]["openCount"] == 1
    assert data["support"]["blockingOpenCount"] == 1
    assert data["nextRequiredAction"] == "resolve_blocking_support"


def test_customer_success_astop_projection_hides_internal_economics_audit_and_expansion_detail(paying_client):
    _record(paying_client)

    serialized = str(snapshot(paying_client)).lower()

    assert "confidential negotiated amount" not in serialized
    assert "internal audit detail" not in serialized
    assert "setter_name" not in serialized
    assert "never expose" not in serialized


def test_astop_success_endpoint_requires_client_plane_and_active_overlay(api_client, paying_client):
    _record(paying_client)
    url = "/api/v1/portal/success/astop/"

    anonymous = api_client.get(url)
    assert anonymous.status_code in {401, 403}

    access = build_tokens_for_client(paying_client)["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    response = api_client.get(url)

    assert response.status_code == 200
    assert response.json()["verifiedValue"] is True
    assert response.json()["entitlementState"] == "active"


def test_success_snapshot_without_astop_does_not_fabricate_deployment_or_value(paying_client):
    data = snapshot(paying_client)

    assert data["astopStage"] == ""
    assert data["ttfvSeconds"] is None
    assert data["verifiedValue"] is False
    assert data["deploymentScope"] is None
    assert data["expansionStatus"] == "not_recorded"
