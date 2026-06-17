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

WEB_RESULT_KEYS = {
    "leadId",
    "tier",
    "scoreBreakdown",
    "productRoute",
    "licensePathway",
    "primaryTechnologies",
    "problemMirror",
    "diagnosis",
    "alphaFitSummary",
    "kpiPreview",
    "proofPreview",
    "recommendedNextStep",
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


def test_primary_technologies_are_canonical_ids():
    lead = _lead_from(REPRESENTATION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    data = ResultPageSerializer(result_obj).data
    assert all(t in {"axiom", "cre", "fqnm"} for t in data["primaryTechnologies"])


def test_product_route_is_display_string():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    data = ResultPageSerializer(result_obj).data
    assert data["productRoute"] in {"ALPHA Compute", "ALPHA Core", "Both"}


def test_diagnosis_rows_have_required_fields():
    lead = _lead_from(EXECUTION_ANSWERS)
    result_obj, _ = ResultGenerator().generate_for_lead(lead)
    for row in result_obj.diagnosis:
        assert {"pressure", "observation", "itrixInterpretation", "alphaRole"}.issubset(row.keys())


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


# ── Endpoint tests (public funnel) ───────────────────────────────────────────
def _qualify(api_client, answers):
    sid = api_client.post("/api/v1/review/sessions/", {"client_id": "rp"}, format="json").json()["id"]
    api_client.post(
        f"/api/v1/review/sessions/{sid}/prompt/",
        {"prompt": "Slow solver", "pressure_areas": ["speed"], "environment": "cae"},
        format="json",
    )
    q = api_client.post(f"/api/v1/review/sessions/{sid}/qualify/", {"answers": answers}, format="json").json()
    return sid, q["lead_id"]


def test_generate_result_endpoint_public(api_client):
    sid, lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    resp = api_client.post(
        "/api/v1/ai/generate-result/", {"lead_id": lead_id, "session_id": sid}, format="json"
    )
    assert resp.status_code == 200
    assert set(resp.json().keys()) == WEB_RESULT_KEYS


def test_get_result_page_public(api_client):
    sid, lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    api_client.post("/api/v1/ai/generate-result/", {"lead_id": lead_id}, format="json")
    resp = api_client.get(f"/api/v1/result-page/{lead_id}/")
    assert resp.status_code == 200
    assert resp.json()["leadId"] == lead_id


def test_get_result_page_by_session_id_resolves(api_client):
    sid, lead_id = _qualify(api_client, EXECUTION_ANSWERS)
    # The web may carry the session id as the (placeholder) lead id.
    resp = api_client.get(f"/api/v1/result-page/{sid}/")
    assert resp.status_code == 200
    assert resp.json()["leadId"] == lead_id


def test_unknown_lead_returns_404(api_client):
    import uuid as _uuid

    resp = api_client.get(f"/api/v1/result-page/{_uuid.uuid4()}/")
    assert resp.status_code == 404
