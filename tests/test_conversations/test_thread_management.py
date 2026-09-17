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


def test_non_owner_and_no_session_cannot_rename():
    owner = ClientFactory()
    thread = thread_svc.create_thread(client=owner, title="Before")

    assert _api(ClientFactory()).patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Stolen"}, format="json"
    ).status_code == 404
    assert _api().patch(
        f"/api/v1/threads/{thread.id}/", {"title": "Anonymous"}, format="json"
    ).status_code == 404
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


def test_anonymous_owner_title_validation_and_manual_title_protection():
    thread = thread_svc.create_thread(visitor_session="sess-owner", title="Before")
    api = _api(session="sess-owner")
    url = f"/api/v1/threads/{thread.id}/"

    assert api.patch(url, {"title": "   "}, format="json").status_code == 400
    assert api.patch(url, {"title": "x" * 201}, format="json").status_code == 400
    assert api.patch(url, {"title": "한국어 수동 제목"}, format="json").status_code == 200

    thread.refresh_from_db()
    thread_svc.set_title_if_unset(thread, "Automatic title")
    thread.refresh_from_db()
    assert thread.title == "한국어 수동 제목"


def test_signed_in_same_browser_can_manage_still_anonymous_thread():
    client_row = ClientFactory()
    thread = thread_svc.create_thread(visitor_session="sess-browser", title="Anonymous before sign-in")
    api = _api(client_row, session="sess-browser")
    url = f"/api/v1/threads/{thread.id}/"

    response = api.patch(url, {"title": "Continued after sign-in"}, format="json")
    assert response.status_code == 200, response.content
    thread.refresh_from_db()
    assert thread.title == "Continued after sign-in"


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


def test_non_owner_and_no_session_cannot_delete(monkeypatch):
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
    assert _api().delete(f"/api/v1/threads/{thread.id}/").status_code == 404
    assert not called
    assert Thread.objects.filter(id=thread.id).exists()


def test_anonymous_owner_delete_purges_bound_attachment(settings, tmp_path, monkeypatch):
    from apps.attachments import storage
    from apps.attachments.models import Attachment, AttachmentStatus
    from apps.attachments.services import retention

    settings.ATTACHMENT_STORAGE_BACKEND = "filesystem"
    settings.ATTACHMENT_BLOB_ROOT = str(tmp_path / "blobs")
    settings.ENABLE_ATTACHMENTS = True

    target = thread_svc.create_thread(visitor_session="sess-owner", title="With attachment")
    keep = thread_svc.create_thread(visitor_session="sess-owner", title="Keep me")
    blob_key = storage.new_blob_key("proof.txt")
    size, digest = storage.write(blob_key, b"anonymous owner attachment")
    Attachment.objects.create(
        thread=target,
        uploaded_by_kind=Attachment.UploadedByKind.SESSION,
        uploaded_by_id="sess-owner",
        filename="proof.txt",
        declared_mime="text/plain",
        detected_mime="text/plain",
        bytes=size,
        sha256=digest,
        blob_key=blob_key,
        status=AttachmentStatus.READY,
    )
    assert storage.exists(blob_key)

    real_purge_thread = retention.purge_thread
    purged: list[str] = []

    def _tracked_purge(thread):
        purged.append(str(thread.id))
        return real_purge_thread(thread)

    monkeypatch.setattr(retention, "purge_thread", _tracked_purge)
    response = _api(session="sess-owner").delete(f"/api/v1/threads/{target.id}/")

    assert response.status_code == 204, response.content
    assert purged == [str(target.id)]
    assert not storage.exists(blob_key)
    assert not Thread.objects.filter(id=target.id).exists()
    assert Thread.objects.filter(id=keep.id).exists()


def test_anonymous_purge_failure_is_truthful_and_keeps_thread(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="sess-owner", title="Keep on purge failure")

    from apps.attachments.services import retention

    def _fail(_thread):
        raise RuntimeError("simulated anonymous storage deletion failure")

    monkeypatch.setattr(retention, "purge_thread", _fail)
    response = _api(session="sess-owner").delete(f"/api/v1/threads/{thread.id}/")

    assert response.status_code == 503
    assert response.json()["code"] == "THREAD_DELETE_FAILED"
    assert "simulated" not in response.json()["detail"]
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
