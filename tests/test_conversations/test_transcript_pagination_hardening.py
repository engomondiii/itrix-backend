from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.conversations.models import Message, SenderKind
from apps.conversations.services import threads as thread_svc
from apps.conversations.views_thread_hardened import latest_seq_for_thread

pytestmark = pytest.mark.django_db

SESSION = "transcript-hardening"


def _api() -> APIClient:
    api = APIClient()
    api.cookies["itrix_visitor_session"] = SESSION
    return api


def _thread():
    return thread_svc.create_thread(visitor_session=SESSION)


def _message(thread, seq: int, body: str = "turn"):
    return Message.objects.create(
        conversation=thread.conversation,
        thread=thread,
        seq=seq,
        sender_kind=SenderKind.VISITOR,
        body=body,
    )


def test_empty_thread_latest_seq_is_zero():
    thread = _thread()
    data = _api().get(f"/api/v1/threads/{thread.id}/messages/").json()
    assert data["messages"] == []
    assert data["latestSeq"] == 0


def test_one_turn_latest_seq_is_that_turn():
    thread = _thread()
    _message(thread, 1)
    data = _api().get(f"/api/v1/threads/{thread.id}/messages/").json()
    assert data["latestSeq"] == 1


def test_paginated_long_thread_preserves_latest_seq_for_whole_thread():
    thread = _thread()
    for seq in range(1, 41):
        _message(thread, seq, f"turn-{seq}")

    data = _api().get(f"/api/v1/threads/{thread.id}/messages/?after_seq=10&limit=5").json()
    assert [row["seq"] for row in data["messages"]] == [11, 12, 13, 14, 15]
    assert data["latestSeq"] == 40


def test_sparse_sequences_report_database_max_not_row_count():
    thread = _thread()
    _message(thread, 2)
    _message(thread, 10)
    data = _api().get(f"/api/v1/threads/{thread.id}/messages/").json()
    assert data["latestSeq"] == 10


@pytest.mark.parametrize("value", ["-1", "0", "501", "abc"])
def test_invalid_transcript_limits_return_customer_safe_400(value):
    thread = _thread()
    res = _api().get(f"/api/v1/threads/{thread.id}/messages/?limit={value}")
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_TRANSCRIPT_LIMIT"
    assert "between 1 and 500" in res.json()["detail"]


@pytest.mark.parametrize("value", ["1", "500"])
def test_valid_transcript_limits_are_accepted(value):
    thread = _thread()
    assert _api().get(f"/api/v1/threads/{thread.id}/messages/?limit={value}").status_code == 200


def test_latest_seq_uses_one_database_max_query_not_python_iteration():
    thread = _thread()
    for seq in (1, 4, 100):
        _message(thread, seq)

    with CaptureQueriesContext(connection) as captured:
        assert latest_seq_for_thread(thread) == 100

    assert len(captured) == 1
    sql = captured[0]["sql"].upper()
    assert "MAX(" in sql
