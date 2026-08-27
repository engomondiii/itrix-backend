"""Review session creation + prompt submission tests (public funnel)."""

from __future__ import annotations

import pytest

from apps.review.models import ReviewSession

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/v1/review/sessions/"
BROWSER = "review-test-browser"


def _bind(api_client, value=BROWSER):
    # Public does not mean unbound. The BFF forwards this anonymous browser/session
    # binding and the backend stores only its digest.
    api_client.credentials(HTTP_X_ITRIX_SESSION=value)
    return api_client


def _create_session(api_client, client_id="c-1", visitor_type="problem_owner"):
    _bind(api_client)
    resp = api_client.post(
        SESSIONS_URL, {"client_id": client_id, "visitor_type": visitor_type}, format="json"
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_review_session_returns_id(api_client):
    body = _create_session(api_client)
    assert "id" in body
    assert body["status"] == "STARTED"
    assert ReviewSession.objects.filter(pk=body["id"]).exists()


def test_create_session_is_public(api_client):
    # Anonymous browser binding is not authentication; no account/JWT is required.
    _bind(api_client)
    resp = api_client.post(SESSIONS_URL, {}, format="json")
    assert resp.status_code == 201


def test_prompt_submit_returns_immediate_response(api_client):
    session = _create_session(api_client)
    url = f"{SESSIONS_URL}{session['id']}/prompt/"
    resp = api_client.post(
        url,
        {
            "prompt": "Our simulation workload is too slow and memory movement dominates.",
            "pressure_areas": ["speed", "memory_data_movement"],
            "environment": "cae",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessionId"] == session["id"]
    assert "immediateResponse" in body
    ir = body["immediateResponse"]
    assert "headline" in ir and "message" in ir
    assert "memory & data movement" in " ".join(
        x for x in [ir["headline"], ir["message"]]
    ) or ir["reflected_pressures"]


def test_prompt_persists_on_session(api_client):
    session = _create_session(api_client)
    url = f"{SESSIONS_URL}{session['id']}/prompt/"
    api_client.post(
        url,
        {"prompt": "Energy cost is rising fast.", "pressure_areas": ["energy", "cost"]},
        format="json",
    )
    obj = ReviewSession.objects.get(pk=session["id"])
    assert obj.prompt == "Energy cost is rising fast."
    assert obj.pressure_areas == ["energy", "cost"]
    assert obj.status == ReviewSession.Status.PROMPTED


def test_empty_prompt_is_rejected(api_client):
    session = _create_session(api_client)
    url = f"{SESSIONS_URL}{session['id']}/prompt/"
    resp = api_client.post(url, {"prompt": ""}, format="json")
    assert resp.status_code == 400


def test_prompt_unknown_session_is_404(api_client):
    import uuid

    _bind(api_client)
    url = f"{SESSIONS_URL}{uuid.uuid4()}/prompt/"
    resp = api_client.post(url, {"prompt": "hello there"}, format="json")
    assert resp.status_code == 404


def test_review_session_uuid_is_not_a_credential(api_client):
    session = _create_session(api_client)
    other_browser = type(api_client)()
    other_browser.credentials(HTTP_X_ITRIX_SESSION="different-browser")
    resp = other_browser.post(
        f"{SESSIONS_URL}{session['id']}/prompt/",
        {"prompt": "Our solver is slow."},
        format="json",
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
