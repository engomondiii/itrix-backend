"""Customer evaluation responses expose final treatment, never internal waiver/risk reasoning."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.evaluations.models import Evaluation, EvaluationPackage, EvaluationStatus
from apps.leads.models import ASTOPEngagement, ASTOPStage
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/portal/evaluation/"


def _authed(row):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(row)['access']}")
    return api


def test_alpha_customer_response_hides_internal_waiver_and_iwl_history():
    client = ClientFactory()
    Evaluation.objects.create(
        lead=client.lead,
        lead_name="Buyer",
        pkg=EvaluationPackage.COMPUTE,
        customer_fee_status="partially_waived",
        final_assessment_fee=Decimal("750"),
        fee_finalized_at=client.created_at,
        ai_waiver_decision="partial",
        waiver_reason="internal strategic reason",
        iwl_override_applied=True,
        iwl_override_reason="internal IWL discussion",
        final_authority="iwl",
    )

    res = _authed(client).get(URL)
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "alpha_compute"
    assert body["customerFeeStatus"] == "partially_waived"
    assert str(body["finalAssessmentFee"]) == "750.00"
    lowered = {str(k).lower() for k in body.keys()}
    assert "waiver_reason" not in lowered and "waiverreason" not in lowered
    assert "iwl_override_reason" not in lowered and "iwloverridereason" not in lowered
    assert "finalauthority" not in lowered


def test_astop_customer_response_exposes_stage_and_verified_value_only():
    client = ClientFactory()
    ASTOPEngagement.objects.create(
        lead=client.lead,
        stage=ASTOPStage.LO_DEPLOYMENT,
        evaluation_result={"decision_fidelity": "passed"},
        security_result={"status": "passed"},
        verified_value={},
    )

    res = _authed(client).get(URL)
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "astop"
    assert body["astopStage"] == "lo_deployment"
    assert "securityResult" not in body
    assert "evaluationResult" not in body


@pytest.mark.parametrize(
    ("internal_status", "customer_stage"),
    [
        (EvaluationStatus.PROPOSED, "requested"),
        (EvaluationStatus.IN_PROGRESS, "in_progress"),
        (EvaluationStatus.DELIVERED, "report_ready"),
        (EvaluationStatus.WON, "report_ready"),
        (EvaluationStatus.LOST, "report_ready"),
    ],
)
def test_alpha_customer_stage_uses_frontend_tracker_vocabulary(internal_status, customer_stage):
    client = ClientFactory()
    Evaluation.objects.create(
        lead=client.lead,
        lead_name="Buyer",
        pkg=EvaluationPackage.COMPUTE,
        status=internal_status,
    )

    res = _authed(client).get(URL)
    assert res.status_code == 200
    assert res.json()["stage"] == customer_stage
