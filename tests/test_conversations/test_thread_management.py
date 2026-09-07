from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.conversations.models_thread import Thread
from apps.conversations.services import threads as thread_svc
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _api(client_row=None, session: str | None = None) -> APIClient:
    api = APIClient()
    if client_row is not None:
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(client_row)['access']}")
    if session:
        api.cookies["itrix_visitor_session"] = session
    return api


def test_owner_can_rename_and_title_persists():
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Before")

    response = _api(owner).patch(
        f"/api/v1/threads/{thread.id}/", {"title": "  한국어 · Renamed!  "}, format="json"
    )

    assert response.status_code == 200, response.content
    thread.refresh_from_db()
    assert thread.title == "한국어 · Renamed!"
    assert response.json()["title"] == "한국어 · Renamed!"
    assert _api(owner).get(f"/api/v1/threads/{thread.id}/").json()["title"] == "한국어 · Renamed!"


def test_blank_and_overlong_titles_are_rejected():
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Before")
    api = _api(owner)

    assert api.patch(f"/api/v1/threads/{thread.id}/", {"title": "   "}, format="json").status_code == 400
    assert api.patch(f"/api/v1/threads/{thread.id}/", {"title": "x" * 201}, format="json").status_code == 400
    thread.refresh_from_db()
    assert thread.title == "Before"


def test_non_owner_and_anonymous_cannot_rename():
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Before")

    assert _api(ClientFactory()).patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Stolen"}, format="json"
    ).status_code == 404
    assert _api().patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Anonymous"}, format="json"
    ).status_code == 401
    thread.refresh_from_db()
    assert thread.title == "Before"


def test_manual_rename_is_not_overwritten_by_automatic_title_generation():
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Before")
    api = _api(owner)
    assert api.patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Manual title"}, format="json"
    ).status_code == 200

    thread.refresh_from_db()
    thread_svc.set_title_if_unset(thread, "Automatic title")
    thread.refresh_from_db()
    assert thread.title == "Manual title"


def test_owner_delete_is_persistent_and_leaves_unrelated_thread(monkeypatch):
    owner = ClientFactory()
    target = thread_svc.create_thread(client=owner, title="Delete me")
    keep = thread_svc.create_thread(client=owner, title="Keep me")
    purged: list[str] = []

    from apps.attachments.services import retention

    monkeypatch.setattr(retention, "purge_thread", lambda thread: purged.append(str(thread.id)) or 0)
    response = _api(owner).delete(f"/api/v1/threads/{target.id}/")

    assert response.status_code == 204, response.content
    assert purged == [str(target.id)]
    assert not Thread.objects.filter(id=target.id).exists()
    assert Thread.objects.filter(id=keep.id).exists()
    ids = [row["threadId"] for row in _api(owner).get("/api/v1/threads/").json()["threads"]]
    assert str(target.id) not in ids
    assert str(keep.id) in ids


def test_non_owner_and_anonymous_cannot_delete(monkeypatch):
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Mine")

    from apps.attachments.services import retention

    called = False

    def _purge(_thread):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(retention, "purge_thread", _purge)
    assert _api(ClientFactory()).delete(f"/api/v1/threads/{thread.id}/").status_code == 404
    assert _api().delete(f"/api/v1/threads/{thread.id}/").status_code == 401
    assert not called
    assert Thread.objects.filter(id=thread.id).exists()


def test_purge_failure_does_not_report_delete_success(monkeypatch):
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Keep on purge failure")

    from apps.attachments.services import retention

    def _fail(_thread):
        raise RuntimeError("simulated storage deletion failure")

    monkeypatch.setattr(retention, "purge_thread", _fail)
    response = _api(owner).delete(f"/api/v1/threads/{thread.id}/")

    assert response.status_code == 503
    assert response.json()["code"] == "THREAD_DELETE_FAILED"
    assert "simulated" not in response.json()["detail"]
    assert Thread.objects.filter(id=thread.id).exists()
