"""Try Again recovery contracts for the two failure classes.

The first request uses a durable Idempotency-Key because the browser may lose the whole
thread-creation response, including the session cookie.  A persisted thread instead uses
``/retry`` and never posts the visitor turn again.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.conversations.models import Message
from apps.conversations.services import ingest, threads as thread_svc
from apps.conversations.views_thread import GenerationAttempt

pytestmark = pytest.mark.django_db


def test_lost_initial_response_replays_same_thread_and_first_turn_once():
    key = "initial-recovery-2df740fb-3e57-45db-8f2f-e54e683613cb"
    payload = {"body": "Help me understand our inference latency."}

    with patch("apps.conversations.views_thread._attempt_assistant_generation", return_value=GenerationAttempt("failed")) as generate:
        first_api = APIClient()
        first = first_api.post(
            "/api/v1/threads/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        assert first.status_code == 201
        thread_id = first.json()["threadId"]

        # Simulate a response lost before Set-Cookie reached the browser: a fresh client has
        # no visitor-session cookie, but it still possesses the high-entropy recovery key.
        retry_api = APIClient()
        replay = retry_api.post(
            "/api/v1/threads/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key
        )

    assert replay.status_code == 200
    assert replay.json()["threadId"] == thread_id
    assert replay["Idempotency-Replayed"] == "true"
    assert "itrix_visitor_session" in replay.cookies
    assert Message.objects.filter(thread_id=thread_id, sender_kind="visitor").count() == 1
    assert generate.call_count == 1, "replay must not repeat the assistant/business action"


def test_initial_idempotency_key_is_bound_to_exact_payload():
    key = "initial-recovery-52cafc9f-a285-4be8-b743-8c0820ec486a"
    with patch("apps.conversations.views_thread._attempt_assistant_generation", return_value=GenerationAttempt("failed")):
        api = APIClient()
        first = api.post(
            "/api/v1/threads/", {"body": "first payload"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        assert first.status_code == 201
        conflict = api.post(
            "/api/v1/threads/", {"body": "different payload"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
    assert conflict.status_code == 409


def test_initial_recovery_key_cannot_cross_an_existing_different_session():
    key = "initial-recovery-c0afcb93-ed14-4163-846c-41e984446456"
    with patch("apps.conversations.views_thread._attempt_assistant_generation", return_value=GenerationAttempt("failed")):
        first = APIClient().post(
            "/api/v1/threads/", {"body": "same"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
        assert first.status_code == 201
        intruder = APIClient()
        intruder.cookies["itrix_visitor_session"] = "different-existing-session"
        denied = intruder.post(
            "/api/v1/threads/", {"body": "same"}, format="json", HTTP_IDEMPOTENCY_KEY=key
        )
    assert denied.status_code == 404


def test_persisted_thread_retry_does_not_repost_visitor_turn_or_duplicate_effects():
    session = "retry-existing-session"
    thread = thread_svc.create_thread(visitor_session=session)
    visitor = ingest.ingest_inbound(
        thread.conversation, sender_kind="visitor", body="Please retry this exact turn", thread=thread
    )
    assert visitor is not None

    api = APIClient()
    api.cookies["itrix_visitor_session"] = session
    fake = {
        "messageId": "assistant-once",
        "senderKind": "agent",
        "body": "Recovered answer",
        "seq": 2,
    }
    before = Message.objects.filter(thread=thread, sender_kind="visitor").count()
    with patch("apps.conversations.views_thread._attempt_assistant_generation", return_value=GenerationAttempt("ready", fake)) as generate:
        res = api.post(f"/api/v1/threads/{thread.id}/retry/", {}, format="json")

    assert res.status_code == 200
    assert res.json()["reused"] is False
    assert Message.objects.filter(thread=thread, sender_kind="visitor").count() == before == 1
    assert generate.call_count == 1
    args, kwargs = generate.call_args
    assert args == (thread, "Please retry this exact turn")
    assert "request_id" in kwargs


def test_persisted_thread_retry_reuses_existing_assistant_without_generation():
    session = "retry-reuse-session"
    thread = thread_svc.create_thread(visitor_session=session)
    ingest.ingest_inbound(thread.conversation, sender_kind="visitor", body="Question", thread=thread)
    ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body="Already answered", thread=thread
    )
    api = APIClient()
    api.cookies["itrix_visitor_session"] = session

    with patch("apps.conversations.views_thread._attempt_assistant_generation") as generate:
        res = api.post(f"/api/v1/threads/{thread.id}/retry/", {}, format="json")

    assert res.status_code == 200
    assert res.json()["reused"] is True
    assert Message.objects.filter(thread=thread, sender_kind="visitor").count() == 1
    assert Message.objects.filter(thread=thread, sender_kind="agent").count() == 1
    generate.assert_not_called()


def test_retry_reports_generation_already_in_progress_as_202():
    session = "retry-pending-session"
    thread = thread_svc.create_thread(visitor_session=session)
    ingest.ingest_inbound(thread.conversation, sender_kind="visitor", body="Question", thread=thread)
    api = APIClient()
    api.cookies["itrix_visitor_session"] = session
    with patch(
        "apps.conversations.views_thread._attempt_assistant_generation",
        return_value=GenerationAttempt("pending"),
    ):
        res = api.post(f"/api/v1/threads/{thread.id}/retry/", {}, format="json")
    assert res.status_code == 202
    assert res.json()["code"] == "GENERATION_ALREADY_IN_PROGRESS"
    assert res.json()["pending"] is True


def test_retry_reports_actual_generation_failure_as_safe_503():
    session = "retry-failed-session"
    thread = thread_svc.create_thread(visitor_session=session)
    ingest.ingest_inbound(thread.conversation, sender_kind="visitor", body="Question", thread=thread)
    api = APIClient()
    api.cookies["itrix_visitor_session"] = session
    with patch(
        "apps.conversations.views_thread._attempt_assistant_generation",
        return_value=GenerationAttempt("failed"),
    ):
        res = api.post(f"/api/v1/threads/{thread.id}/retry/", {}, format="json")
    assert res.status_code == 503
    body = res.json()
    assert body["code"] == "MODEL_GENERATION_FAILED"
    assert body["retryable"] is True
    assert "traceback" not in str(body).lower()
