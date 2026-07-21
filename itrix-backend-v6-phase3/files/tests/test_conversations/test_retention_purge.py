"""
Thread retention and verifiable purge (Backend v6.0 §Phase 3, Architecture §10.3).

    A visitor who never creates an account keeps their threads for the anonymous-session
    retention window AND NO LONGER.

Deleting rows is not a purge. A purge is verifiable when the thread, its messages, its
artifacts and its attachment blobs are ALL demonstrably gone.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.conversations.models import Message, Thread
from apps.conversations.services import ingest, retention, threads as thread_svc

pytestmark = pytest.mark.django_db


def _expired_thread(session="s-retain", turns=2):
    thread = thread_svc.create_thread(visitor_session=session)
    for i in range(turns):
        ingest.ingest_inbound(thread.conversation, sender_kind="visitor",
                              body=f"turn {i}", thread=thread)
    Thread.objects.filter(id=thread.id).update(
        retention_expires_at=timezone.now() - timezone.timedelta(days=1)
    )
    thread.refresh_from_db()
    return thread


def test_expired_threads_are_identified():
    _expired_thread()
    assert retention.expired_threads().count() == 1


def test_an_unexpired_thread_is_left_alone():
    thread_svc.create_thread(visitor_session="s-fresh")
    assert retention.expired_threads().count() == 0


def test_a_claimed_thread_is_never_purged():
    """The client's contractual retention takes over — a paying customer keeps history."""
    from apps.conversations.models import ThreadOwnerKind

    thread = _expired_thread()
    Thread.objects.filter(id=thread.id).update(
        claimed_at=timezone.now(), owner_kind=ThreadOwnerKind.CLIENT
    )
    assert retention.expired_threads().count() == 0


def test_purge_removes_the_thread_and_its_messages():
    thread = _expired_thread()
    thread_id = thread.id
    retention.purge_thread(thread)
    assert not Thread.objects.filter(id=thread_id).exists()
    assert not Message.objects.filter(thread_id=thread_id).exists()


def test_purge_removes_derived_artifacts():
    from apps.journey.constants import ARTIFACT_REFLECTION
    from apps.journey.models_artifacts import Artifact
    from apps.journey.services import artifacts

    thread = _expired_thread()
    artifacts.generate(thread, ARTIFACT_REFLECTION, force=True)
    thread_id = thread.id
    retention.purge_thread(thread)
    assert not Artifact.objects.filter(thread_id=thread_id).exists()


def test_purge_removes_attachment_blobs(settings, tmp_path):
    """
    A cascade delete on the row would leave the FILE on disk — the exact failure the
    retention guarantee exists to prevent.
    """
    settings.ATTACHMENT_BLOB_ROOT = str(tmp_path / "blobs")
    settings.ENABLE_ATTACHMENTS = True

    from apps.attachments import storage
    from apps.attachments.services import intake

    thread = _expired_thread()
    attachment = intake.stage(thread=thread, filename="x.txt", data=b"secret",
                              declared_mime="text/plain")
    blob_key = attachment.blob_key
    assert storage.exists(blob_key)

    retention.purge_thread(thread)
    assert not storage.exists(blob_key)


def test_verify_confirms_every_trace_is_gone():
    thread = _expired_thread()
    thread_id = str(thread.id)
    retention.purge_thread(thread)
    report = retention.verify_purged(thread_id)
    assert report["verified"] is True
    assert report["thread_gone"] and report["messages_gone"]


def test_verify_can_actually_fail():
    """A verifier that cannot fail proves nothing."""
    thread = _expired_thread()
    assert retention.verify_purged(str(thread.id))["verified"] is False


def test_export_produces_the_full_transcript():
    """
    A visitor can ask for their conversation BEFORE it expires. Offering an export only
    after the purge would be offering nothing.
    """
    thread = _expired_thread(turns=3)
    payload = retention.export_thread(thread)
    assert payload["threadId"] == str(thread.id)
    assert len(payload["messages"]) == 3


def test_the_export_excludes_halted_messages():
    """
    A halted message's partial text was discarded on purpose. Exporting it would deliver
    exactly the text the guard stopped.
    """
    from apps.conversations.models import StreamingStatus

    thread = _expired_thread(turns=1)
    ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body="Alpha is 30% faster",
        thread=thread, streaming_status=StreamingStatus.HALTED,
    )
    bodies = [m["body"] for m in retention.export_thread(thread)["messages"]]
    assert "Alpha is 30% faster" not in bodies


def test_the_sweep_purges_everything_due():
    _expired_thread(session="a")
    _expired_thread(session="b")
    summary = retention.sweep()
    assert summary["purged"] == 2
    assert summary["failed"] == 0


def test_a_dry_run_changes_nothing():
    thread = _expired_thread()
    summary = retention.sweep(dry_run=True)
    assert summary["dry_run"] is True
    assert summary["purged"] == 0
    assert Thread.objects.filter(id=thread.id).exists()


def test_the_management_command_reports_without_purging():
    from io import StringIO

    from django.core.management import call_command

    thread = _expired_thread()
    out = StringIO()
    call_command("purge_anonymous_threads", "--report", stdout=out)
    assert "past their retention window" in out.getvalue()
    assert Thread.objects.filter(id=thread.id).exists()


def test_the_command_purges_when_asked():
    from io import StringIO

    from django.core.management import call_command

    thread = _expired_thread()
    call_command("purge_anonymous_threads", "--purge", stdout=StringIO())
    assert not Thread.objects.filter(id=thread.id).exists()
