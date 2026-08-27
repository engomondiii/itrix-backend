"""Browser-bound, one-time My Review access regressions.

The review-session UUID and lead UUID are identifiers, not credentials.  Surface 1 gets a
short-lived opaque exchange code only after READY; the BFF exchanges it once and keeps the
resulting access-session token in an httpOnly cookie.  These backend tests pin the binding,
reuse, expiry and legacy-route properties that make forwarded links non-authorizing.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.result_page.models import ClientPageAccessGrant, ResultPage
from apps.result_page.services.client_access import issue_for_lead
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _ready_lead():
    lead = LeadFactory(journey_state="CLIENT_PAGE")
    ResultPage.objects.create(
        lead=lead,
        generation_status=ResultPage.GenerationStatus.READY,
        problem_mirror_structured={
            "statedFacts": ["A representative workload was described."],
            "affectedDecision": "Whether to run a bounded evaluation.",
            "consequence": "The current cost/latency trade-off needs evidence.",
            "boundedHypothesis": "A representation boundary may be worth testing.",
            "unknowns": ["Frozen baseline"],
            "confirmOrCorrect": "Confirm or correct this reading.",
            "controls": [],
        },
        diagnosis=[
            {
                "title": "Bounded workload",
                "observation": "Representative workload",
                "interpretation": "Candidate boundary; not yet a finding.",
                "evidenceStatus": "Conversation-specific",
            }
        ],
        alpha_fit_summary="A bounded representation review may be evaluated on the existing stack.",
        kpi_preview=[{"label": "Latency", "metric": "p95/p99"}],
        proof_preview=[],
        recommended_next_step="Confirm the review scope.",
    )
    return lead


def _client(browser: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_X_ITRIX_SESSION=browser)
    return client


def _exchange(client: APIClient, code: str):
    return client.post("/api/v1/client-page/access/exchange/", {"code": code}, format="json")


def test_valid_browser_can_exchange_once_and_read_tokenless_review():
    lead = _ready_lead()
    code = issue_for_lead(lead, visitor_session="browser-a")
    assert str(lead.id) not in code
    assert "." not in code  # opaque code, not a JWT

    browser = _client("browser-a")
    exchanged = _exchange(browser, code)
    assert exchanged.status_code == 200
    raw_session = exchanged.json()["sessionToken"]
    assert raw_session
    assert str(lead.id) not in raw_session

    browser.credentials(
        HTTP_X_ITRIX_SESSION="browser-a",
        HTTP_X_ITRIX_CLIENT_PAGE_SESSION=raw_session,
    )
    page = browser.get("/api/v1/client-page/current/")
    assert page.status_code == 200
    body = page.json()
    for forbidden in (
        "leadId", "lead_id", "tier", "score", "scoreBreakdown", "productRoute",
        "licensePathway", "primaryTechnologies", "personaId", "confidence", "relevance",
    ):
        assert forbidden not in body


def test_forwarded_exchange_code_fails_for_wrong_browser_without_consuming_it():
    lead = _ready_lead()
    code = issue_for_lead(lead, visitor_session="browser-a")

    forwarded = _exchange(_client("browser-b"), code)
    assert forwarded.status_code == 404
    assert forwarded.json()["error"]["code"] == "access_unavailable"

    # A failed forwarded attempt does not burn the legitimate recipient's one-time code.
    legitimate = _exchange(_client("browser-a"), code)
    assert legitimate.status_code == 200


def test_exchange_code_cannot_be_reused_after_success():
    lead = _ready_lead()
    code = issue_for_lead(lead, visitor_session="browser-a")
    browser = _client("browser-a")
    assert _exchange(browser, code).status_code == 200
    reused = _exchange(browser, code)
    assert reused.status_code == 404
    assert reused.json()["error"]["code"] == "access_unavailable"


def test_access_session_is_bound_to_the_same_browser():
    lead = _ready_lead()
    code = issue_for_lead(lead, visitor_session="browser-a")
    session_token = _exchange(_client("browser-a"), code).json()["sessionToken"]

    wrong = _client("browser-b")
    wrong.credentials(
        HTTP_X_ITRIX_SESSION="browser-b",
        HTTP_X_ITRIX_CLIENT_PAGE_SESSION=session_token,
    )
    response = wrong.get("/api/v1/client-page/current/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "access_unavailable"


def test_expired_revoked_and_malformed_codes_fail_with_the_same_safe_shape():
    lead = _ready_lead()
    browser = _client("browser-a")

    expired = issue_for_lead(lead, visitor_session="browser-a")
    ClientPageAccessGrant.objects.filter(lead=lead).update(expires_at=timezone.now() - timedelta(seconds=1))
    expired_response = _exchange(browser, expired)
    assert expired_response.status_code == 404

    revoked = issue_for_lead(lead, visitor_session="browser-a")
    ClientPageAccessGrant.objects.filter(lead=lead, consumed_at__isnull=True).update(revoked_at=timezone.now())
    revoked_response = _exchange(browser, revoked)
    assert revoked_response.status_code == 404

    malformed_response = _exchange(browser, "not-a-real-code")
    assert malformed_response.status_code == 404

    shapes = [expired_response.json(), revoked_response.json(), malformed_response.json()]
    assert all(item == shapes[0] for item in shapes)


def test_legacy_token_url_is_a_410_tombstone():
    response = _client("browser-a").get("/api/v1/client-page/looks-like-a-token/")
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "legacy_access_retired"
