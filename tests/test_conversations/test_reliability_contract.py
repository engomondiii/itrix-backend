"""Conversation rate-limit, safe-error, persistence and ownership reliability contracts."""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from django.core.cache import cache

from apps.conversations.models import Message
from apps.conversations.services import threads as thread_svc
from apps.conversations.views_thread import GenerationAttempt

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolate_rate_limit_cache():
    """Rate-limit tests vary ceilings, so no IP/session counter may leak between cases."""
    cache.clear()
    yield
    cache.clear()


def _api(session: str) -> APIClient:
    api = APIClient()
    api.cookies["itrix_visitor_session"] = session
    return api


def test_new_chat_does_not_bypass_existing_turn_rate_limit(settings):
    settings.ANON_TURNS_PER_HOUR = 1
    session = "same-budget-session"
    thread = thread_svc.create_thread(visitor_session=session)
    api = _api(session)
    with patch(
        "apps.conversations.views_thread._attempt_assistant_generation",
        return_value=GenerationAttempt("ready", None),
    ):
        allowed = api.post(
            f"/api/v1/threads/{thread.id}/turns/", {"body": "first"}, format="json"
        )
        blocked_existing = api.post(
            f"/api/v1/threads/{thread.id}/turns/", {"body": "second"}, format="json"
        )
        blocked_new = api.post("/api/v1/threads/", {"body": "new chat"}, format="json")

    assert allowed.status_code == 201
    for response in (blocked_existing, blocked_new):
        assert response.status_code == 429
        assert response.json()["code"] == "RATE_LIMITED"
        assert int(response["Retry-After"]) > 0


def test_first_turn_and_existing_turn_share_rate_limit_shape(settings):
    settings.ANON_TURNS_PER_HOUR = 0
    # A zero ceiling means the very first turn is blocked on either endpoint.
    session = "first-subsequent-shape"
    api = _api(session)
    thread = thread_svc.create_thread(visitor_session=session)
    existing = api.post(f"/api/v1/threads/{thread.id}/turns/", {"body": "x"}, format="json")
    fresh = api.post("/api/v1/threads/", {"body": "x"}, format="json")
    assert existing.status_code == fresh.status_code == 429
    assert existing.json()["code"] == fresh.json()["code"] == "RATE_LIMITED"


def test_idempotent_first_turn_replay_is_before_rate_budget(settings):
    settings.ANON_TURNS_PER_HOUR = 1
    session = "idempotent-budget-session"
    api = _api(session)
    key = "idem-rate-9b970419-56d5-438c-a825-b28ae9e006db"
    with patch(
        "apps.conversations.views_thread._attempt_assistant_generation",
        return_value=GenerationAttempt("ready", None),
    ):
        first = api.post(
            "/api/v1/threads/", {"body": "same"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        replay = api.post(
            "/api/v1/threads/", {"body": "same"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay["Idempotency-Replayed"] == "true"
    assert Message.objects.filter(thread_id=first.json()["threadId"], sender_kind="visitor").count() == 1


def test_generation_failure_keeps_persisted_visitor_turn_and_reports_status():
    session = "generation-failed-turn"
    thread = thread_svc.create_thread(visitor_session=session)
    api = _api(session)
    with patch(
        "apps.conversations.views_thread._attempt_assistant_generation",
        return_value=GenerationAttempt("failed"),
    ):
        response = api.post(
            f"/api/v1/threads/{thread.id}/turns/",
            {"body": "Please keep this even if generation fails."},
            format="json",
        )
    assert response.status_code == 201
    body = response.json()
    assert body["generationStatus"] == "failed"
    assert body["generationError"]["code"] == "MODEL_GENERATION_FAILED"
    assert body["assistantTurn"] is None
    assert Message.objects.filter(
        thread=thread,
        sender_kind="visitor",
        body="Please keep this even if generation fails.",
    ).count() == 1


def test_inaccessible_thread_uses_safe_code_and_preserves_request_id():
    request_id = "req-reliability-12345678"
    response = APIClient().get(
        f"/api/v1/threads/{uuid4()}/", HTTP_X_REQUEST_ID=request_id
    )
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "THREAD_NOT_FOUND_OR_INACCESSIBLE"
    assert body["requestId"] == request_id
    assert response["X-Request-ID"] == request_id
    rendered = str(body).lower()
    assert "traceback" not in rendered and "token" not in rendered and "database" not in rendered


def test_anonymous_different_session_cannot_access_thread():
    owner = "owner-session"
    thread = thread_svc.create_thread(visitor_session=owner)
    response = _api("different-session").get(f"/api/v1/threads/{thread.id}/")
    assert response.status_code == 404
    assert response.json()["code"] == "THREAD_NOT_FOUND_OR_INACCESSIBLE"
