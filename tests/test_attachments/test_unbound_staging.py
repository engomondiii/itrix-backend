"""
THE ARRIVAL-SCREEN ATTACHMENT (2026-08-13).

A visitor attaches a document on the landing page, before typing anything. There is no
Thread at that moment, so `POST attachments/` arrived with no `thread_id` — and the upload
view required one, returning 404 `{"detail": "Not found."}`. The composer rendered that
under the filename as "28 KB · Not found.", so a working upload looked like a lost file.

`Attachment.thread` is now nullable and the file is staged against the UPLOADER until the
first turn creates a thread. That widens where an attachment can exist, so the boundary it
could weaken is pinned here rather than left to the feature test:

    §4.6 boundary 3 — an attachment is scoped to its thread.

During the unbound window the scope is the session or client that staged it, and binding
is one-way. `test_a_stranger_cannot_claim_an_unbound_attachment` and
`test_binding_across_threads_is_refused` are the two ways that could have gone wrong.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

SESSION_COOKIE = "itrix_visitor_session"


@pytest.fixture(autouse=True)
def _flag(settings, tmp_path):
    settings.ATTACHMENT_BLOB_ROOT = str(tmp_path / "blobs")
    settings.ENABLE_ATTACHMENTS = True


def _file(name: str = "workload.txt", body: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        body if body is not None else b"our CFD solver stalls on boundary exchange " * 40,
        content_type="text/plain",
    )


def _stage(client: APIClient, name: str = "workload.txt"):
    """Upload with NO thread_id — exactly what the arrival composer sends."""
    return client.post("/api/v1/attachments/", {"file": _file(name)}, format="multipart")


# ── THE BUG, AS A TEST ───────────────────────────────────────────────────────


def test_a_first_time_visitor_can_attach_before_a_thread_exists():
    """THE REGRESSION. No session, no thread — this returned 404 'Not found.'."""
    res = _stage(APIClient())

    assert res.status_code == 201, res.data
    assert res.data["attachmentId"]


def test_attachment_processing_stays_inline_when_global_celery_is_enabled(settings):
    """Railway Celery may stay on while local attachment blobs remain web-service local."""
    from apps.attachments.models import Attachment, AttachmentExtraction, AttachmentStatus

    settings.ENABLE_CELERY = True
    settings.ATTACHMENT_PROCESS_INLINE = True

    res = _stage(APIClient(), "celery-safe.txt")

    assert res.status_code == 201, res.data
    attachment = Attachment.objects.get(id=res.data["attachmentId"])
    assert attachment.status == AttachmentStatus.READY
    assert attachment.scans.filter(verdict="clean").exists()
    assert AttachmentExtraction.objects.filter(attachment=attachment).exists()


def test_a_returning_visitor_with_a_session_can_attach_before_a_thread():
    client = APIClient()
    client.cookies[SESSION_COOKIE] = "sess-returning"

    assert _stage(client).status_code == 201


def test_the_upload_stages_unbound_and_records_the_uploader():
    from apps.attachments.models import Attachment

    client = APIClient()
    client.cookies[SESSION_COOKIE] = "sess-owner"
    attachment = Attachment.objects.get(id=_stage(client).data["attachmentId"])

    assert attachment.thread_id is None
    assert attachment.uploaded_by_kind == Attachment.UploadedByKind.SESSION
    assert attachment.uploaded_by_id == "sess-owner"


def test_an_unbound_upload_mints_the_session_it_is_owned_by():
    """
    Attaching can be the visitor's FIRST action. Without a session issued here the turn
    that follows would arrive as a different visitor and could never claim the file.
    """
    res = _stage(APIClient())

    assert SESSION_COOKIE in res.cookies
    assert res.cookies[SESSION_COOKIE].value


def test_the_uploader_can_read_an_unbound_attachment_back():
    client = APIClient()
    attachment_id = _stage(client).data["attachmentId"]

    assert client.get(f"/api/v1/attachments/{attachment_id}/").status_code == 200


def test_a_supplied_thread_id_is_still_checked():
    """Widening the ABSENT case must not widen the WRONG case."""
    import uuid

    client = APIClient()
    client.cookies[SESSION_COOKIE] = "sess-nothread"
    res = client.post(
        "/api/v1/attachments/",
        {"file": _file(), "thread_id": str(uuid.uuid4())},
        format="multipart",
    )

    assert res.status_code == 404


# ── THE HAND-OFF ─────────────────────────────────────────────────────────────


def test_creating_a_thread_binds_the_staged_attachment_and_links_the_first_turn():
    """
    `ThreadCreateSerializer.attachment_ids` has existed since v6.0 and was never read, so
    the file stayed unbound, no MessageAttachment row was written, and `for_context` —
    which selects by THREAD — never saw it. The visitor got an answer that ignored the
    document they had just watched upload.
    """
    from apps.attachments.models import Attachment
    from apps.conversations.models import MessageAttachment

    client = APIClient()
    attachment_id = _stage(client).data["attachmentId"]

    created = client.post(
        "/api/v1/threads/",
        {"body": "Our CFD solver stalls on boundary exchange.", "attachment_ids": [attachment_id]},
        format="json",
    )
    assert created.status_code == 201

    attachment = Attachment.objects.get(id=attachment_id)
    assert str(attachment.thread_id) == created.data["threadId"]
    assert MessageAttachment.objects.filter(attachment_id=attachment_id).count() == 1


def test_a_bound_attachment_reaches_the_model_context():
    """The point of the whole feature: the agent can actually see the file."""
    from apps.attachments.services import excerpts
    from apps.conversations.models_thread import Thread

    client = APIClient()
    attachment_id = _stage(client, "solver-notes.txt").data["attachmentId"]
    thread_id = client.post(
        "/api/v1/threads/",
        {"body": "Where is the boundary cost?", "attachment_ids": [attachment_id]},
        format="json",
    ).data["threadId"]

    context = excerpts.for_context(Thread.objects.get(id=thread_id), "boundary exchange")

    assert [item["filename"] for item in context] == ["solver-notes.txt"]


def test_submitting_a_turn_links_the_attachment():
    """`threads/{id}/turns/` put the ids in `meta` and never wrote the link."""
    from apps.conversations.models import MessageAttachment

    client = APIClient()
    thread_id = client.post("/api/v1/threads/", {"body": "opening"}, format="json").data["threadId"]
    attachment_id = _stage(client, "second.txt").data["attachmentId"]

    res = client.post(
        f"/api/v1/threads/{thread_id}/turns/",
        {"body": "here is the profile", "attachment_ids": [attachment_id]},
        format="json",
    )

    assert res.status_code == 201
    assert MessageAttachment.objects.filter(attachment_id=attachment_id).count() == 1


def test_binding_is_idempotent_so_a_retried_submit_is_safe():
    from apps.attachments.models import Attachment

    client = APIClient()
    thread_id = client.post("/api/v1/threads/", {"body": "opening"}, format="json").data["threadId"]
    attachment_id = _stage(client).data["attachmentId"]

    for _ in range(2):
        res = client.post(
            f"/api/v1/threads/{thread_id}/turns/",
            {"body": "retry", "attachment_ids": [attachment_id]},
            format="json",
        )
        assert res.status_code == 201

    assert str(Attachment.objects.get(id=attachment_id).thread_id) == thread_id


def test_an_unknown_attachment_id_never_costs_the_visitor_their_turn():
    """A bad id costs that FILE. The sentence they typed is not negotiable."""
    import uuid

    client = APIClient()
    res = client.post(
        "/api/v1/threads/",
        {"body": "this sentence must survive", "attachment_ids": [str(uuid.uuid4())]},
        format="json",
    )

    assert res.status_code == 201


# ── THE BOUNDARY (§4.6 rule 3) ───────────────────────────────────────────────


def test_a_stranger_cannot_claim_an_unbound_attachment():
    """
    THE RISK THE NULLABLE FK CREATES. An unbound attachment has no thread to be scoped
    to, so if the scope did not fall back to the UPLOADER, naming somebody else's
    attachment id would carry their document into your conversation — where the excerpt
    selector would feed it to the model.
    """
    from apps.attachments.models import Attachment
    from apps.conversations.models import MessageAttachment

    victim = APIClient()
    attachment_id = _stage(victim, "confidential.txt").data["attachmentId"]

    attacker = APIClient()
    attacker.cookies[SESSION_COOKIE] = "sess-attacker"

    assert attacker.get(f"/api/v1/attachments/{attachment_id}/").status_code == 404
    assert attacker.delete(f"/api/v1/attachments/{attachment_id}/").status_code == 404

    stolen = attacker.post(
        "/api/v1/threads/",
        {"body": "give me their file", "attachment_ids": [attachment_id]},
        format="json",
    )
    assert stolen.status_code == 201  # their own turn is fine
    assert Attachment.objects.get(id=attachment_id).thread_id is None  # the file is not
    assert MessageAttachment.objects.filter(attachment_id=attachment_id).count() == 0


def test_binding_across_threads_is_refused():
    """One attachment, one thread, for its whole life — even for its own uploader."""
    from apps.attachments.models import Attachment

    client = APIClient()
    attachment_id = _stage(client).data["attachmentId"]
    first = client.post(
        "/api/v1/threads/", {"body": "first", "attachment_ids": [attachment_id]}, format="json"
    ).data["threadId"]
    second = client.post(
        "/api/v1/threads/", {"body": "second", "attachment_ids": [attachment_id]}, format="json"
    ).data["threadId"]

    assert first != second
    assert str(Attachment.objects.get(id=attachment_id).thread_id) == first


def test_association_refuses_an_attachment_from_another_thread():
    """
    `associate_attachments` used to link whatever id it was given. That was safe only
    because its two callers filtered first; the public thread routes now call it too.
    """
    from apps.attachments.services import intake
    from apps.conversations.models import Message, MessageAttachment
    from apps.conversations.services import ingest, threads as thread_svc

    mine = thread_svc.create_thread(visitor_session="sess-mine")
    theirs = thread_svc.create_thread(visitor_session="sess-theirs")
    foreign = intake.stage(
        thread=theirs, filename="theirs.txt", data=b"x" * 64, uploaded_by_id="sess-theirs"
    )

    message = ingest.ingest_inbound(
        mine.conversation, sender_kind="visitor", body="mine", thread=mine
    )
    linked = ingest.associate_attachments(message, [str(foreign.id)])

    assert linked == 0
    assert MessageAttachment.objects.filter(attachment_id=foreign.id).count() == 0
    assert Message.objects.filter(id=message.id).exists()  # the turn still stands


def test_a_team_caller_must_name_a_thread():
    """Staff attach INTO a conversation. An unbound team file no query could reach."""
    from tests.factories.user_factory import AdminUserFactory

    client = APIClient()
    client.force_authenticate(user=AdminUserFactory(email="staff-unbound@itrix.test"))

    assert _stage(client).status_code == 400
