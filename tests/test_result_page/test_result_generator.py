"""Result-page generator + endpoint tests — must match the web ResultPage contract."""

from __future__ import annotations

import pytest

from apps.leads.services.lead_creator import LeadCreator
from apps.result_page.models import ResultPage
from apps.result_page.serializers import ResultPageSerializer
from apps.result_page.services.result_generator import ResultGenerator
from apps.routing.services.license_router import route_license
from apps.routing.services.product_router import route_product
from apps.scoring.services.scorer import LeadScorer
from tests.factories.review_factory import ReviewSessionFactory
from tests.factories.scoring_factory import EXECUTION_ANSWERS, REPRESENTATION_ANSWERS

pytestmark = pytest.mark.django_db

# Customer-facing My Review contract. Internal lead ids, scores, routes, hidden
# technology selection and commercial pathway are deliberately absent.
WEB_RESULT_KEYS = {
    "problemMirror",
    "diagnosis",
    "alphaFitSummary",
    "kpiPreview",
    "proofPreview",
    "recommendedNextStep",
    "generationStatus",
    "artifactFamily",
    "artifactVersion",
    "generatedAt",
    "locale",
}



def _lead_from(answers):
    session = ReviewSessionFactory(prompt="Our solver is slow.", pressure_areas=["speed"])
    score = LeadScorer.score(answers)
    return LeadCreator.create_from_review(
        session,
        answers=answers,
        score_breakdown=score.breakdown,
        score_total=score.total,
        tier=score.tier,
        product_route=route_product(answers),
        license_pathway=route_license(answers),
    )


def test_generates_and_persists_result_page():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, report = ResultGenerator().generate_for_lead(lead)
    assert isinstance(result_obj, ResultPage)
    assert ResultPage.objects.filter(lead=lead).count() == 1
    assert "used_ai" in report


def test_serialized_result_matches_web_contract():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    data = ResultPageSerializer(result_obj).data
    assert set(data.keys()) == WEB_RESULT_KEYS


def test_internal_route_fields_are_retained_server_side_but_not_serialized():
    lead = _lead_from(REPRESENTATION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    assert all(t in {"axiom", "cre", "fqnm"} for t in result_obj.primary_technologies)
    from apps.leads.models import PRODUCT_ROUTE_DISPLAY
    assert result_obj.product_route in set(PRODUCT_ROUTE_DISPLAY.values())
    assert result_obj.product_route == "Not yet assessed"
    data = ResultPageSerializer(result_obj).data
    for forbidden in ("leadId", "primaryTechnologies", "productRoute", "licensePathway", "tier", "score"):  # noqa: E501
        assert forbidden not in data


def test_diagnosis_rows_use_human_readable_customer_schema():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    for row in result_obj.diagnosis:
        assert {"title", "observation", "interpretation", "evidenceStatus"}.issubset(row.keys())
        assert "alphaRole" not in row


def test_proof_preview_only_public_or_nda():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    for proof in result_obj.proof_preview:
        assert proof["disclosure"] in {"public", "nda_only"}


def test_regeneration_is_idempotent_one_per_lead():
    lead = _lead_from(EXECUTION_ANSWERS)
    ResultGenerator().generate_for_lead(lead)
    ResultGenerator().generate_for_lead(lead)
    assert ResultPage.objects.filter(lead=lead).count() == 1


# ── Legacy/public endpoint retirement and access-bound flow ───────────────────
def _qualify(api_client, answers):
    from apps.review.models import ReviewSession

    api_client.credentials(HTTP_X_ITRIX_SESSION="result-test-browser")
    sid = api_client.post("/api/v1/review/sessions/", {"client_id": "rp"}, format="json").json()["id"]
    api_client.post(
        f"/api/v1/review/sessions/{sid}/prompt/",
        {"prompt": "Slow solver", "pressure_areas": ["speed"], "environment": "cae"},
        format="json",
    )
    # These access/retirement tests do not exercise background review generation.
    # Prevent a daemon DB worker from escaping the pytest-django transaction and
    # reporting a thread exception after the test has already finished.
    from unittest.mock import patch

    with patch("apps.review.services.qualification_processor.kick_off_result_page"):
        response = api_client.post(
            f"/api/v1/review/sessions/{sid}/qualify/", {"answers": answers}, format="json"
        )
    assert response.status_code == 200
    session = ReviewSession.objects.get(pk=sid)
    return sid, str(session.placeholder_lead_id)


def test_legacy_public_generate_result_endpoint_is_retired(api_client):
    sid, lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    resp = api_client.post(
        "/api/v1/ai/generate-result/", {"lead_id": lead_id, "session_id": sid}, format="json"
    )
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "legacy_generation_retired"


def test_result_page_by_lead_uuid_is_not_public(api_client):
    _sid, lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    resp = api_client.get(f"/api/v1/result-page/{lead_id}/")
    assert resp.status_code in (401, 403)


def test_result_page_by_review_session_uuid_is_not_public(api_client):
    sid, _lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    resp = api_client.get(f"/api/v1/result-page/{sid}/")
    assert resp.status_code in (401, 403)


def test_result_detail_does_not_enumerate_random_ids_to_anonymous_users(api_client):
    import uuid as _uuid

    resp = api_client.get(f"/api/v1/result-page/{_uuid.uuid4()}/")
    assert resp.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 regression: the public page must not expose internal scoring
# ─────────────────────────────────────────────────────────────────────────────
def test_the_public_result_page_exposes_no_tier_or_score():
    """
    THE REGRESSION. This endpoint is AllowAny; these fields are §10.5 internal-only.

    Pinned as its own test rather than only as a key-set comparison, so the intent
    survives even if someone later relaxes the exact-match assertion above.
    """
    from apps.result_page.serializers import ResultPageSerializer

    fields = set(ResultPageSerializer.Meta.fields)
    for forbidden in ("tier", "scoreBreakdown", "score", "score_breakdown"):
        assert forbidden not in fields, f"{forbidden} is exposed on the public result page"
