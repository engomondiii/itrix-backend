"""Focused management-reporting regressions (team plane only)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.services import management_reporting
from apps.clients.tokens import build_tokens_for_client
from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.leads.models import ASTOPEngagement, ASTOPStage, TrustStatus
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.review_factory import ReviewSessionFactory, VisitorSessionFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def test_acquisition_counts_by_source():
    VisitorSessionFactory(source_channel="organic")
    VisitorSessionFactory(source_channel="partner")
    LeadFactory(acquisition_context={"source_channel": "organic"})
    LeadFactory(acquisition_context={"source_channel": "organic"})
    LeadFactory(acquisition_context={"source_channel": "partner"})

    acquisition = management_reporting.summary()["acquisition"]

    assert acquisition["trafficBySource"] == {"organic": 1, "partner": 1}
    assert acquisition["leadsBySource"] == {"organic": 2, "partner": 1}


def test_visitor_to_lead_conversion_uses_actual_review_linkage():
    converted = VisitorSessionFactory(source_channel="organic")
    VisitorSessionFactory(source_channel="organic")
    review = ReviewSessionFactory(visitor_session=converted)
    LeadFactory(review_session=review, acquisition_context={"source_channel": "organic"})

    conversion = management_reporting.summary()["acquisition"]["visitorToLead"]

    assert conversion == {
        "visitorSessions": 2,
        "convertedVisitorSessions": 1,
        "conversionRate": 0.5,
    }


def test_screening_pass_review_reject_counts():
    LeadFactory(trust_status=TrustStatus.PASS)
    LeadFactory(trust_status=TrustStatus.REVIEW, escalated=True)
    LeadFactory(trust_status=TrustStatus.REJECT, escalated=True)
    LeadFactory(trust_status=TrustStatus.UNREVIEWED)

    trust = management_reporting.summary()["trust"]

    assert trust["pass"] == 1
    assert trust["review"] == 1
    assert trust["reject"] == 1
    assert trust["escalated"] == 2
    assert trust["screenedLeads"] == 3
    assert trust["screeningCoverageRate"] == 0.75
    assert trust["passRateAmongScreened"] == 0.3333


def test_astop_stage_counts():
    for stage in (
        ASTOPStage.IDENTIFY_QUALIFY,
        ASTOPStage.NDA_BRIEFING,
        ASTOPStage.CONTROLLED_EVALUATION,
        ASTOPStage.LO_DEPLOYMENT,
        ASTOPStage.VERIFY_EXPAND,
    ):
        ASTOPEngagement.objects.create(lead=LeadFactory(), stage=stage)

    stages = management_reporting.summary()["astop"]["stageCounts"]

    assert stages[ASTOPStage.IDENTIFY_QUALIFY] == 1
    assert stages[ASTOPStage.NDA_BRIEFING] == 1
    assert stages[ASTOPStage.CONTROLLED_EVALUATION] == 1
    assert stages[ASTOPStage.LO_DEPLOYMENT] == 1
    assert stages[ASTOPStage.VERIFY_EXPAND] == 1


def test_astop_qualified_to_evaluation_conversion():
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.NDA_BRIEFING)
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.CONTROLLED_EVALUATION)
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.LO_DEPLOYMENT)
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.VERIFY_EXPAND)

    astop = management_reporting.summary()["astop"]

    assert astop["qualifiedProspects"] == 4
    assert astop["qualifiedToEvaluationConversionRate"] == 0.75


def test_astop_evaluation_to_lo_conversion():
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.CONTROLLED_EVALUATION)
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.LO_DEPLOYMENT)
    ASTOPEngagement.objects.create(lead=LeadFactory(), stage=ASTOPStage.VERIFY_EXPAND)

    astop = management_reporting.summary()["astop"]

    assert astop["evaluationToLoConversionRate"] == 0.6667


def test_ttfv_ignores_incomplete_and_invalid_records():
    now = timezone.now()
    ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        authorized_install_at=now,
        reproducible_value_at=now + timedelta(seconds=90),
    )
    ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        authorized_install_at=now,
        reproducible_value_at=None,
    )
    ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        authorized_install_at=now,
        reproducible_value_at=now - timedelta(seconds=1),
    )

    ttfv = management_reporting.summary()["astop"]["ttfv"]

    assert ttfv["validRecordCount"] == 1
    assert ttfv["averageSeconds"] == 90.0
    assert ttfv["medianSeconds"] == 90


def _proof_record(*, measured, estimated=None):
    return ASTOPEngagement.objects.create(
        lead=LeadFactory(),
        stage=ASTOPStage.VERIFY_EXPAND,
        evaluation_scope={
            "workload": "bounded-workload",
            "observation_behavior": "controlled-observation",
            "model_or_controller": "controller-v1",
            "workflow": "reproducible-workflow",
        },
        baseline={"measurement_window": "60m"},
        decision_fidelity={"status": "passed"},
        measured_savings=measured,
        estimated_savings=estimated or {},
        security_result={"status": "passed"},
        integration_feasibility={"status": "passed"},
        evaluation_result={"status": "passed", "reproducible": True},
        verified_value={"status": "verified"},
    )


def test_measured_value_excludes_estimated_only_results():
    _proof_record(measured={"value": 0, "provenance": "metered-run"})
    _proof_record(
        measured={"value": None},
        estimated={"value": 25, "provenance": "modelled-estimate"},
    )

    astop = management_reporting.summary()["astop"]

    assert astop["verifiedValueCount"] == 2
    assert astop["governedMeasuredValueCount"] == 1


def test_waiver_none_partial_full_counts():
    for decision in (WaiverType.NONE, WaiverType.PARTIAL, WaiverType.FULL):
        Evaluation.objects.create(
            lead=LeadFactory(),
            pkg=EvaluationPackage.COMPUTE,
            ai_waiver_decision=decision,
            waiver_type=decision,
        )

    alpha = management_reporting.summary()["alphaCompute"]

    assert alpha["aiNoWaiver"] == 1
    assert alpha["aiPartialWaiver"] == 1
    assert alpha["aiFullWaiver"] == 1


def test_iwl_override_count():
    Evaluation.objects.create(
        lead=LeadFactory(),
        pkg=EvaluationPackage.COMPUTE,
        iwl_override_applied=True,
        iwl_override_status=WaiverType.PARTIAL,
    )
    Evaluation.objects.create(lead=LeadFactory(), pkg=EvaluationPackage.COMPUTE)

    alpha = management_reporting.summary()["alphaCompute"]

    assert alpha["iwlOverrides"] == 1


def test_final_authority_distinguishes_ai_and_iwl():
    finalized = timezone.now()
    Evaluation.objects.create(
        lead=LeadFactory(),
        pkg=EvaluationPackage.COMPUTE,
        fee_finalized_at=finalized,
        final_authority="ai",
        iwl_override_applied=False,
    )
    Evaluation.objects.create(
        lead=LeadFactory(),
        pkg=EvaluationPackage.COMPUTE,
        fee_finalized_at=finalized,
        final_authority="iwl",
        iwl_override_applied=True,
    )

    alpha = management_reporting.summary()["alphaCompute"]

    assert alpha["finalAuthority"]["ai"] == 1
    assert alpha["finalAuthority"]["iwl"] == 1
    assert alpha["noOverrideFinalizations"] == 1


def test_management_endpoint_requires_internal_team_authentication(api_client):
    anonymous = api_client.get("/api/v1/analytics/management/")
    assert anonymous.status_code in {401, 403}

    api_client.force_authenticate(user=AdminUserFactory())
    team = api_client.get("/api/v1/analytics/management/")
    assert team.status_code == 200
    assert "acquisition" in team.json()
    assert "astop" in team.json()


def test_client_plane_token_cannot_access_management_analytics(api_client):
    client = ClientFactory()
    token = build_tokens_for_client(client)["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = api_client.get("/api/v1/analytics/management/")

    assert response.status_code in {401, 403}
