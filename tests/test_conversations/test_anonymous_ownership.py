"""
Anonymous thread ownership over HTTP (Backend v6.0 §2.2, §7.1).

"PUBLIC" means unauthenticated, not unprotected. Guessing a thread id gets a 404 because
the query filters on your session — not because the id was hard to guess.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

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
    assert len(turns) == 1
    assert "HBM" in turns[0]["body"]
    assert turns[0]["seq"] == 1


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
    assert "sidebar_sections" in shell
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


def test_a_visitor_can_rename_and_delete_their_thread():
    thread = thread_svc.create_thread(visitor_session="sess-owner")
    client = _client()
    client.cookies["itrix_visitor_session"] = "sess-owner"

    assert client.patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Renamed"}, format="json"
    ).data["title"] == "Renamed"
    assert client.delete(f"/api/v1/threads/{thread.id}/").status_code == 204
    assert client.get(f"/api/v1/threads/{thread.id}/").status_code == 404
