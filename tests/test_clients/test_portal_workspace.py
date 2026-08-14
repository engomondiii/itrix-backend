"""
Portal workspace endpoints — the shapes the screens render (2026-08-10).

Three reported failures, one root pattern: the portal screens were built to a
richer contract than the views returned, and nobody had signed in to notice
until open registration shipped.

  · Documents crashed: the screen maps `openFolders` / `dataRoomFolders`; the
    view sent a flat `documents` list.
  · Settings crashed: the screen renders {profile, team, notifications}; the
    view sent a flat profile, and the team-invite route did not exist.
  · Sending a message 405'd: the screen has always POSTed to the messages
    route; the view only implemented GET. Attachments ride that same send.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch
from django.test import override_settings
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.conversations.services.history import get_or_create_portal_conversation
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _authed(client_row) -> APIClient:
    api = APIClient()
    token = build_tokens_for_client(client_row)["access"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


# ─────────────────────────────────────────────────────────────────────────────
# Documents — the folder shape
# ─────────────────────────────────────────────────────────────────────────────
def test_documents_payload_carries_the_folder_arrays_the_screen_maps():
    row = ClientFactory()
    res = _authed(row).get("/api/v1/portal/documents/")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data["openFolders"], list) and data["openFolders"]
    assert isinstance(data["dataRoomFolders"], list) and data["dataRoomFolders"]
    first = data["openFolders"][0]
    assert "folder" in first and isinstance(first["documents"], list)


def test_data_room_documents_lock_until_the_nda_is_signed():
    row = ClientFactory(nda_signed=False)
    data = _authed(row).get("/api/v1/portal/documents/").json()
    locked = [d["locked"] for f in data["dataRoomFolders"] for d in f["documents"]]
    assert locked and all(locked)

    row.nda_signed = True
    row.save(update_fields=["nda_signed"])
    data = _authed(row).get("/api/v1/portal/documents/").json()
    unlocked = [d["locked"] for f in data["dataRoomFolders"] for d in f["documents"]]
    assert unlocked and not any(unlocked)


# ─────────────────────────────────────────────────────────────────────────────
# Settings — profile · team · notifications
# ─────────────────────────────────────────────────────────────────────────────
def test_settings_payload_is_the_nested_shape_the_screen_renders():
    row = ClientFactory(full_name="Ada L", organization="GPSLAB", role="Engineer")
    data = _authed(row).get("/api/v1/portal/settings/").json()
    assert data["profile"]["fullName"] == "Ada L"
    assert data["profile"]["email"] == row.email
    assert data["team"][0] == {"email": row.email, "status": "active"}
    assert set(data["notifications"]) == {
        "newTeamMessage", "reviewUpdated", "evalOrPocStatus", "documentShared",
    }
    assert all(data["notifications"].values())  # defaults ON


def test_settings_patch_updates_profile_and_notifications():
    row = ClientFactory()
    api = _authed(row)
    data = api.patch(
        "/api/v1/portal/settings/",
        {"profile": {"fullName": "Grace H"}, "notifications": {"documentShared": False}},
        format="json",
    ).json()
    assert data["profile"]["fullName"] == "Grace H"
    assert data["notifications"]["documentShared"] is False
    assert data["notifications"]["newTeamMessage"] is True  # untouched keys keep defaults

    row.refresh_from_db()
    assert row.full_name == "Grace H"
    assert row.notification_prefs["documentShared"] is False


def test_team_invite_records_and_lists_the_invitation():
    row = ClientFactory()
    api = _authed(row)
    from apps.emails.models import EmailLog
    email_log = EmailLog.objects.create(
        kind=EmailLog.Kind.VISITOR,
        to_email="ally@example.com",
        subject="invite",
        status=EmailLog.Status.STUBBED,
    )
    with patch("apps.emails.services.team_invite_builder.send_email", return_value=email_log) as send:
        res = api.post("/api/v1/portal/settings/team/invite/", {"email": "Ally@Example.com"}, format="json")
        assert res.status_code == 201
        team = res.json()["team"]
        assert {"email": "ally@example.com", "status": "invited"} in team

        # Idempotent in storage, but a repeated invite deliberately resends the email.
        res = api.post("/api/v1/portal/settings/team/invite/", {"email": "ally@example.com"}, format="json")
        assert res.status_code == 201
        assert sum(1 for m in res.json()["team"] if m["email"] == "ally@example.com") == 1
        assert send.call_count == 2


@override_settings(ENABLE_EMAIL_DELIVERY=True)
def test_team_invite_is_not_listed_when_delivery_fails():
    from apps.clients.models import ClientTeamInvite
    from apps.emails.models import EmailLog

    row = ClientFactory()
    failed = EmailLog.objects.create(
        kind=EmailLog.Kind.VISITOR,
        to_email="ally@example.com",
        subject="invite",
        status=EmailLog.Status.FAILED,
        error="smtp unavailable",
    )
    with patch(
        "apps.emails.services.team_invite_builder.build_team_invite_email",
        return_value=failed,
    ):
        res = _authed(row).post(
            "/api/v1/portal/settings/team/invite/", {"email": "ally@example.com"}, format="json"
        )
    assert res.status_code == 503
    assert not ClientTeamInvite.objects.filter(client=row, email="ally@example.com").exists()


def test_team_invite_refuses_the_owner_and_junk():
    row = ClientFactory()
    api = _authed(row)
    assert api.post("/api/v1/portal/settings/team/invite/", {"email": row.email}, format="json").status_code == 400
    assert api.post("/api/v1/portal/settings/team/invite/", {"email": "not-an-email"}, format="json").status_code == 400


def test_messaging_inbox_excludes_ai_review_conversations():
    from apps.conversations.models import Conversation, ConversationContext

    row = ClientFactory()
    portal = get_or_create_portal_conversation(row)
    Conversation.objects.create(
        context=ConversationContext.REVIEW, client=row, lead=row.lead, title="AI review"
    )
    data = _authed(row).get("/api/v1/portal/conversations/").json()
    assert [item["id"] for item in data] == [str(portal.id)]


# ─────────────────────────────────────────────────────────────────────────────
# Messages — the POST the screen was already calling
# ─────────────────────────────────────────────────────────────────────────────
def _conversation_for(row):
    conv = get_or_create_portal_conversation(row)
    return conv


def test_portal_get_exposes_the_thread_id_for_the_composer():
    row = ClientFactory()
    conv = _conversation_for(row)
    data = _authed(row).get(f"/api/v1/portal/conversations/{conv.id}/messages/").json()
    assert data["threadId"], "the composer stages attachments against this id"


def test_portal_send_persists_the_client_message():
    row = ClientFactory()
    conv = _conversation_for(row)
    res = _authed(row).post(
        f"/api/v1/portal/conversations/{conv.id}/messages/", {"body": "Hello team"}, format="json"
    )
    assert res.status_code == 201
    msg = res.json()
    assert msg["senderKind"] == "client"
    assert msg["body"] == "Hello team"
    assert msg["attachments"] == []

    thread = _authed(row).get(f"/api/v1/portal/conversations/{conv.id}/messages/").json()
    assert any(m["body"] == "Hello team" for m in thread["messages"])


def test_portal_send_refuses_an_empty_turn():
    row = ClientFactory()
    conv = _conversation_for(row)
    res = _authed(row).post(f"/api/v1/portal/conversations/{conv.id}/messages/", {"body": "  "}, format="json")
    assert res.status_code == 400


def test_portal_send_is_scoped_to_the_owning_client():
    row, intruder = ClientFactory(), ClientFactory()
    conv = _conversation_for(row)
    res = _authed(intruder).post(
        f"/api/v1/portal/conversations/{conv.id}/messages/", {"body": "hi"}, format="json"
    )
    assert res.status_code == 404


def test_messaging_endpoint_refuses_an_ai_review_conversation():
    from apps.conversations.models import Conversation, ConversationContext

    row = ClientFactory()
    review = Conversation.objects.create(
        context=ConversationContext.REVIEW, client=row, lead=row.lead, title="AI review"
    )
    api = _authed(row)
    assert api.get(f"/api/v1/portal/conversations/{review.id}/messages/").status_code == 404
    assert api.post(
        f"/api/v1/portal/conversations/{review.id}/messages/", {"body": "wrong channel"}, format="json"
    ).status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Attachments on the client plane
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ATTACHMENTS=True)
def test_client_can_stage_a_file_against_their_portal_thread_and_send_it():
    from django.core.files.uploadedfile import SimpleUploadedFile

    row = ClientFactory()
    conv = _conversation_for(row)
    api = _authed(row)
    thread_id = api.get(f"/api/v1/portal/conversations/{conv.id}/messages/").json()["threadId"]

    up = api.post(
        "/api/v1/attachments/",
        {"file": SimpleUploadedFile("notes.txt", b"our workload notes", content_type="text/plain"),
         "thread_id": thread_id},
        format="multipart",
    )
    assert up.status_code == 201, up.content
    attachment_id = up.json()["attachmentId"]

    sent = api.post(
        f"/api/v1/portal/conversations/{conv.id}/messages/",
        {"body": "Attached our notes", "attachmentIds": [attachment_id]},
        format="json",
    )
    assert sent.status_code == 201
    atts = sent.json()["attachments"]
    assert [a["attachmentId"] for a in atts] == [attachment_id]
    assert atts[0]["filename"] == "notes.txt"


@override_settings(ENABLE_ATTACHMENTS=True)
def test_a_stranger_cannot_stage_a_file_against_someone_elses_thread():
    from django.core.files.uploadedfile import SimpleUploadedFile

    row, intruder = ClientFactory(), ClientFactory()
    conv = _conversation_for(row)
    thread_id = _authed(row).get(f"/api/v1/portal/conversations/{conv.id}/messages/").json()["threadId"]

    res = _authed(intruder).post(
        "/api/v1/attachments/",
        {"file": SimpleUploadedFile("x.txt", b"x", content_type="text/plain"), "thread_id": thread_id},
        format="multipart",
    )
    assert res.status_code == 404
