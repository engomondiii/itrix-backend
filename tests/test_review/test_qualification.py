"""Qualification scoring / routing / tier tests (Phase 1 initial form)."""

from __future__ import annotations

import pytest

from apps.review.models import ReviewSession
from apps.review.services.qualification_processor import (
    classify_tier,
    route_license,
    route_product,
    score_answers,
)
from tests.factories.review_factory import (
    HIGH_SCORE_ANSWERS,
    LOW_SCORE_ANSWERS,
    ReviewSessionFactory,
)

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/v1/review/sessions/"


# ── Pure-function tests (must mirror the frontend exactly) ───────────────────
def test_score_caps_per_category_and_total():
    breakdown, total = score_answers(HIGH_SCORE_ANSWERS)
    assert breakdown["strategic_fit"] <= 25
    assert breakdown["technical_fit"] <= 25
    assert breakdown["urgency"] <= 20
    assert breakdown["budget_authority"] <= 15
    assert breakdown["license_potential"] <= 15
    assert total <= 100
    assert total == sum(breakdown.values())


def test_high_score_answers_land_tier_1():
    _, total = score_answers(HIGH_SCORE_ANSWERS)
    tier, label = classify_tier(total)
    assert total >= 80
    assert tier == 1
    assert label == "Strategic"


def test_low_score_answers_land_tier_4():
    _, total = score_answers(LOW_SCORE_ANSWERS)
    tier, _label = classify_tier(total)
    assert tier == 4


def test_product_router_representation_to_compute():
    answers = {"Q3": "linear_algebra", "Q1": "python_scipy", "Q2": []}
    assert route_product(answers) == "alpha_compute"


def test_product_router_execution_to_core():
    answers = {"Q3": "conservation", "Q1": "hardware", "Q2": ["hardware_utilization"]}
    assert route_product(answers) == "alpha_core"


def test_product_router_mixed_to_both():
    assert route_product({"Q3": "mixed"}) == "both"


def test_product_router_unsure_to_general():
    assert route_product({"Q3": "unsure"}) == "general"


def test_license_router_exclusive_hardware_to_strategic():
    assert route_license({"Q9": "exclusive", "Q6": "hardware_chip"}) == "strategic"


def test_license_router_non_exclusive():
    assert route_license({"Q9": "non_exclusive", "Q6": "research"}) == "non_exclusive"


def test_license_router_product_only_is_none():
    assert route_license({"Q9": "product_only"}) is None


# ── Endpoint test: qualify returns authoritative result + placeholder lead ───
def _start_session(api_client):
    resp = api_client.post(SESSIONS_URL, {"client_id": "q-1"}, format="json")
    return resp.json()["id"]


def test_qualify_endpoint_returns_full_result(api_client):
    sid = _start_session(api_client)
    url = f"{SESSIONS_URL}{sid}/qualify/"
    resp = api_client.post(url, {"answers": HIGH_SCORE_ANSWERS}, format="json")
    assert resp.status_code == 200
    body = resp.json()

    assert body["lead_id"]  # real lead id present (Phase 2)
    assert body["lead_is_placeholder"] is False
    assert body["tier"] == 1
    assert body["product_route"] in {"alpha_compute", "alpha_core", "both", "general"}
    assert body["score"]["total"] >= 80
    assert set(body["score"]["breakdown"].keys()) == {
        "strategic_fit",
        "technical_fit",
        "urgency",
        "budget_authority",
        "license_potential",
    }


def test_qualify_marks_session_qualified(api_client):
    sid = _start_session(api_client)
    url = f"{SESSIONS_URL}{sid}/qualify/"
    api_client.post(url, {"answers": LOW_SCORE_ANSWERS}, format="json")
    obj = ReviewSession.objects.get(pk=sid)
    assert obj.status == ReviewSession.Status.QUALIFIED
    assert obj.score_total is not None
    assert obj.placeholder_lead_id is not None


def test_qualify_requires_answers(api_client):
    sid = _start_session(api_client)
    url = f"{SESSIONS_URL}{sid}/qualify/"
    resp = api_client.post(url, {"answers": {}}, format="json")
    assert resp.status_code == 400


def test_processor_persists_with_factory_session():
    session = ReviewSessionFactory()
    from apps.review.services.qualification_processor import process_qualification

    result = process_qualification(session, HIGH_SCORE_ANSWERS)
    assert result.lead_id == str(session.placeholder_lead_id)
    assert result.tier == 1
