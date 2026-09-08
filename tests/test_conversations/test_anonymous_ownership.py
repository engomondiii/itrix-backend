"""
Anonymous thread ownership over HTTP (Backend v6.0 §2.2, §7.1).

"PUBLIC" means unauthenticated, not unprotected. Guessing a thread id gets a 404 because
the query filters on your session — not because the id was hard to guess.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.conversations.models_thread import Thread
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db


def _client():
    return APIClient()


def test_creating_a_thread_issues_a_session_cookie():
    response = _client().post("/api/v1/threads/", {}, format="json")
    assert response.status_code == 201
    assert "itrix_visitor_session" in response.cookies


def test_the_first_prompt_becomes_turn_one():
    """
    R12: the first prompt IS the first review turn. No screen anywhere asks the visitor
    to restate the sentence they already typed.
    """
    response = _client().post(
        "/api/v1/threads/", {"body": "Our HBM traffic saturates the fleet"}, format="json"
    )
    assert response.status_code == 201
    turns = response.data["turns"]

    # Turn 1 is the visitor's own sentence, verbatim and at seq 1.
    assert turns[0]["senderKind"] == "visitor"
    assert "HBM" in turns[0]["body"]
    assert turns[0]["seq"] == 1

    # v6.0 delivery fix: the assistant answers in the SAME response rather than
    # waiting for a socket that may never connect. So a second turn is expected
    # — but only ever an assistant one, and only after the visitor's.
    assert len(turns) <= 2
    if len(turns) == 2:
        assert turns[1]["senderKind"] == "agent"
        assert turns[1]["seq"] == 2


def test_another_session_cannot_read_your_thread():
    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-attacker"
    assert client.get(f"/api/v1/threads/{thread.id}/").status_code == 404


def test_the_owning_session_can_read_it():
    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"
    response = client.get(f"/api/v1/threads/{thread.id}/")
    assert response.status_code == 200
    assert response.data["threadId"] == str(thread.id)


def test_the_shell_contract_is_returned_with_the_thread():
    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"
    shell = client.get(f"/api/v1/threads/{thread.id}/").data["shell"]
    assert shell["journey_state"] == 1
    # v7.1 Phase 3: the v6.0 alias is gone; the two zone fields are what clients read.
    assert "sidebar_sections" not in shell
    assert "conversation_rail_sections" in shell
    assert "content_pane_sections" in shell
    assert "left_rail" not in shell
    assert "right_rail" not in shell


def test_listing_is_scoped_to_the_session():
    thread_svc.create_thread(visitor_session="sess-a")
    thread_svc.create_thread(visitor_session="sess-b")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-a"
    assert len(client.get("/api/v1/threads/").data["threads"]) == 1


def test_no_session_lists_nothing_rather_than_erroring():
    response = _client().get("/api/v1/threads/")
    assert response.status_code == 200
    assert response.data["threads"] == []


def test_an_oversized_turn_returns_413_with_a_recoverable_message():
    from django.conf import settings

    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"
    response = client.post(
        f"/api/v1/threads/{thread.id}/turns/",
        {"body": "x" * (settings.MAX_MESSAGE_CHARS + 1)},
        format="json",
    )
    assert response.status_code == 413
    assert "nothing you have already written is lost" in str(response.data["detail"])


def test_a_twenty_thousand_character_turn_is_accepted():
    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"
    response = client.post(
        f"/api/v1/threads/{thread.id}/turns/", {"body": "x" * 20_000}, format="json"
    )
    assert response.status_code == 201


def test_anonymous_owner_can_read_rename_and_delete_their_thread():
    target = thread_svc.create_thread(visitor_session="sess-owner", title="Before")
    keep = thread_svc.create_thread(visitor_session="sess-owner", title="Keep me")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"
    url = f"/api/v1/threads/{target.id}/"

    before = client.get(url)
    assert before.status_code == 200
    assert before.data["threadId"] == str(target.id)

    rename = client.patch(url, {"title": "  한국어 · Anonymous owner  "}, format="json")
    assert rename.status_code == 200, rename.content
    assert rename.data["threadId"] == str(target.id)
    assert rename.data["title"] == "한국어 · Anonymous owner"
    assert set(rename.data).issubset(
        {"threadId", "title", "titleSource", "context", "lastActivityAt"}
    )

    target.refresh_from_db()
    assert target.title == "한국어 · Anonymous owner"
    assert client.get(url).data["title"] == "한국어 · Anonymous owner"

    delete = client.delete(url)
    assert delete.status_code == 204, delete.content
    assert not Thread.objects.filter(id=target.id).exists()
    assert Thread.objects.filter(id=keep.id).exists()
    assert client.get(url).status_code == 404


def test_cross_session_and_no_session_cannot_mutate_anonymous_owned_thread():
    thread = thread_svc.create_thread(visitor_session="sess-owner", title="Owner title")
    url = f"/api/v1/threads/{thread.id}/"

    other = _client()
    other.cookies["itrix_visitor_session"] = "sess-other"
    assert other.patch(url, {"title": "Stolen"}, format="json").status_code == 404
    assert other.delete(url).status_code == 404

    no_session = _client()
    assert no_session.patch(url, {"title": "Guessed"}, format="json").status_code == 404
    assert no_session.delete(url).status_code == 404

    thread.refresh_from_db()
    assert thread.title == "Owner title"
