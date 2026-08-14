"""
The client plane of the thread views (2026-08-10).

`list_for_client` / `get_for_client` existed since the spine shipped, and every
session filter excludes claimed threads (`client__isnull=True`) — but no view
ever authenticated a client, so a signed-in customer could neither list nor
reopen their own conversations, and the workspace had to bolt a second rail on
top of the public surface to show anything at all. These tests pin the plane:
who sees what, that signing in never hides a conversation, and that a
customer's new chat is client-owned from birth.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.conversations.services import threads as thread_svc
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db

SESSION = "sess-client-plane-1"


def _api(client_row=None, session: str | None = None) -> APIClient:
    api = APIClient()
    if client_row is not None:
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(client_row)['access']}")
    if session:
        api.cookies["itrix_visitor_session"] = session
    return api


def test_a_clients_threads_are_listed_on_the_client_plane():
    row = ClientFactory()
    mine = thread_svc.create_thread(client=row, title="My claimed review")
    other = ClientFactory()
    thread_svc.create_thread(client=other, title="Somebody else's")

    data = _api(row).get("/api/v1/threads/").json()
    ids = [t["threadId"] for t in data["threads"]]
    assert str(mine.id) in ids
    assert len(ids) == 1


def test_signing_in_never_hides_the_sessions_own_threads():
    """The union: client-owned PLUS the browser's still-anonymous threads."""
    row = ClientFactory()
    owned = thread_svc.create_thread(client=row, title="Owned")
    anon = thread_svc.create_thread(visitor_session=SESSION, title="Pre-signup")

    ids = [t["threadId"] for t in _api(row, session=SESSION).get("/api/v1/threads/").json()["threads"]]
    assert str(owned.id) in ids and str(anon.id) in ids


def test_the_session_plane_is_unchanged():
    anon = thread_svc.create_thread(visitor_session=SESSION, title="Anon")
    thread_svc.create_thread(client=ClientFactory(), title="Client-owned")

    ids = [t["threadId"] for t in _api(session=SESSION).get("/api/v1/threads/").json()["threads"]]
    assert ids == [str(anon.id)]


def test_a_clients_new_chat_is_client_owned_from_birth():
    row = ClientFactory()
    res = _api(row, session=SESSION).post("/api/v1/threads/", {"body": ""}, format="json")
    assert res.status_code == 201
    thread_id = res.json()["threadId"]

    from apps.conversations.models_thread import Thread, ThreadOwnerKind

    t = Thread.objects.get(id=thread_id)
    assert t.client_id == row.id
    assert t.owner_kind == ThreadOwnerKind.CLIENT
    # And it lists on the client plane — including from a DIFFERENT device.
    ids = [x["threadId"] for x in _api(row).get("/api/v1/threads/").json()["threads"]]
    assert thread_id in ids


def test_a_client_can_open_and_speak_on_their_thread_from_any_device():
    row = ClientFactory()
    t = thread_svc.create_thread(client=row, title="Mine")
    api = _api(row)  # no session cookie at all — a fresh device

    assert api.get(f"/api/v1/threads/{t.id}/").status_code == 200
    turn = api.post(f"/api/v1/threads/{t.id}/turns/", {"body": "picking this back up"}, format="json")
    assert turn.status_code in (200, 201), turn.content


def test_strangers_are_refused_on_both_planes():
    row = ClientFactory()
    t = thread_svc.create_thread(client=row, title="Mine")

    assert _api(ClientFactory()).get(f"/api/v1/threads/{t.id}/").status_code == 404
    assert _api(session="some-other-session").get(f"/api/v1/threads/{t.id}/").status_code == 404


def test_a_signed_in_customer_can_still_open_their_pre_signup_thread():
    row = ClientFactory()
    anon = thread_svc.create_thread(visitor_session=SESSION, title="Pre-signup")
    assert _api(row, session=SESSION).get(f"/api/v1/threads/{anon.id}/").status_code == 200


def test_portal_messaging_thread_is_not_listed_as_an_ai_conversation():
    from apps.conversations.services.history import ensure_portal_thread, get_or_create_portal_conversation

    row = ClientFactory()
    ai = thread_svc.create_thread(client=row, title="My AI review")
    portal = get_or_create_portal_conversation(row)
    messaging = ensure_portal_thread(portal, row)

    ids = [t["threadId"] for t in _api(row).get("/api/v1/threads/").json()["threads"]]
    assert str(ai.id) in ids
    assert str(messaging.id) not in ids


def test_pre_signup_ai_thread_remains_visible_after_sign_in_while_portal_is_hidden():
    from apps.conversations.services.history import ensure_portal_thread, get_or_create_portal_conversation

    row = ClientFactory()
    pre_signup = thread_svc.create_thread(visitor_session=SESSION, title="Before account")
    portal = get_or_create_portal_conversation(row)
    messaging = ensure_portal_thread(portal, row)

    ids = [t["threadId"] for t in _api(row, session=SESSION).get("/api/v1/threads/").json()["threads"]]
    assert str(pre_signup.id) in ids
    assert str(messaging.id) not in ids


def test_portal_messaging_thread_cannot_be_opened_through_ai_thread_routes():
    from apps.conversations.services.history import ensure_portal_thread, get_or_create_portal_conversation

    row = ClientFactory()
    messaging = ensure_portal_thread(get_or_create_portal_conversation(row), row)
    api = _api(row)
    assert api.get(f"/api/v1/threads/{messaging.id}/").status_code == 404
    assert api.post(
        f"/api/v1/threads/{messaging.id}/turns/", {"body": "wrong surface"}, format="json"
    ).status_code == 404
