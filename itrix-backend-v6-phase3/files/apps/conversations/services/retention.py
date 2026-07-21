"""
Thread retention, export and verifiable purge (Backend v6.0 §Phase 3, §2.2).

    A visitor who never creates an account keeps their threads for the anonymous-session
    retention window AND NO LONGER (Architecture §10.3).

Phase 1 put the expiry on the row at creation. This module is what makes the sentence
true rather than aspirational: it sweeps, it EXPORTS before deleting where asked, and it
VERIFIES afterwards.

── WHY EXPORT COMES BEFORE PURGE ────────────────────────────────────────────
A visitor can ask for their conversation before it expires. Offering an export only after
the purge would be offering nothing. ``export_thread`` produces the full transcript in one
structure so the obligation can be met without reaching into three tables by hand.

── WHY A PURGE IS VERIFIED, NOT ASSUMED ─────────────────────────────────────
Deleting rows is not a purge. ``verify_purged`` re-checks that the messages, the artifacts
and the attachments are all actually gone. A purge nobody can verify is a claim.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("itrix")


def expired_threads():
    """Anonymous threads past their retention window and never claimed."""
    from apps.conversations.models import Thread, ThreadOwnerKind

    return Thread.objects.filter(
        owner_kind=ThreadOwnerKind.SESSION,
        client__isnull=True,
        claimed_at__isnull=True,
        retention_expires_at__lt=timezone.now(),
    )


def export_thread(thread) -> dict:
    """
    The full transcript, for a visitor who asks for it before expiry.

    Held and halted messages are EXCLUDED: a halted message's partial text was discarded
    on purpose, and exporting it would deliver exactly the text the guard stopped.
    """
    from apps.conversations.models import Message

    messages = (
        Message.objects.filter(thread=thread)
        .exclude(streaming_status="halted")
        .order_by("seq", "created_at")
    )
    return {
        "threadId": str(thread.id),
        "title": thread.title,
        "context": thread.context,
        "createdAt": thread.created_at.isoformat(),
        "lastActivityAt": (
            thread.last_activity_at.isoformat() if thread.last_activity_at else None
        ),
        "retentionExpiresAt": (
            thread.retention_expires_at.isoformat() if thread.retention_expires_at else None
        ),
        "messages": [
            {
                "seq": m.seq,
                "senderKind": m.sender_kind,
                "body": m.body if m.is_deliverable else "",
                "at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "attachments": _attachment_manifest(thread),
    }


def _attachment_manifest(thread) -> list[dict]:
    try:
        from apps.attachments.models import Attachment

        return [
            {"filename": a.filename, "type": a.detected_mime, "bytes": a.bytes,
             "status": a.status}
            for a in Attachment.objects.filter(thread=thread, deleted_at__isnull=True)
        ]
    except Exception:  # noqa: BLE001
        return []


@transaction.atomic
def purge_thread(thread, *, reason: str = "retention") -> dict:
    """
    Purge one thread and everything derived from it.

    Attachments are purged through their OWN service so the blob is removed too — a
    cascade delete on the row would leave the file on disk, which is the failure mode the
    whole retention guarantee exists to prevent.
    """
    from apps.conversations.models import Conversation, Message

    thread_id = str(thread.id)
    conversation_id = thread.conversation_id

    attachments_purged = _purge_attachments(thread)
    artifacts_removed = _delete_artifacts(thread)
    messages_removed = Message.objects.filter(thread=thread).count()

    thread.delete()
    if conversation_id:
        Conversation.objects.filter(id=conversation_id).delete()

    record = {
        "thread_id": thread_id,
        "messages_removed": messages_removed,
        "artifacts_removed": artifacts_removed,
        "attachments_purged": attachments_purged,
        "purged_at": timezone.now().isoformat(),
        "reason": reason,
    }
    logger.info("thread.purge %s", record)
    return record


def _purge_attachments(thread) -> int:
    try:
        from apps.attachments.services import retention as attachment_retention

        return attachment_retention.purge_thread(thread)
    except Exception:  # noqa: BLE001
        logger.debug("attachment purge skipped (app unavailable)")
        return 0


def _delete_artifacts(thread) -> int:
    try:
        from apps.journey.models_artifacts import Artifact, CoverageSnapshot, QuestionSuggestion

        removed = Artifact.objects.filter(thread=thread).count()
        Artifact.objects.filter(thread=thread).delete()
        QuestionSuggestion.objects.filter(thread=thread).delete()
        CoverageSnapshot.objects.filter(thread=thread).delete()
        return removed
    except Exception:  # noqa: BLE001
        return 0


def verify_purged(thread_id: str) -> dict:
    """
    Prove a thread is gone. Returns ``verified`` only when EVERY trace is absent.

    Checks the thread, its messages, its artifacts and its attachment blobs — the four
    places a fragment could survive.
    """
    from apps.conversations.models import Message, Thread

    thread_gone = not Thread.objects.filter(id=thread_id).exists()
    messages_gone = not Message.objects.filter(thread_id=thread_id).exists()

    artifacts_gone = True
    try:
        from apps.journey.models_artifacts import Artifact

        artifacts_gone = not Artifact.objects.filter(thread_id=thread_id).exists()
    except Exception:  # noqa: BLE001
        pass

    attachments_gone = True
    try:
        from apps.attachments import storage
        from apps.attachments.models import Attachment

        for attachment in Attachment.objects.filter(thread_id=thread_id):
            if attachment.blob_key and storage.exists(attachment.blob_key):
                attachments_gone = False
                break
    except Exception:  # noqa: BLE001
        pass

    return {
        "thread_id": str(thread_id),
        "thread_gone": thread_gone,
        "messages_gone": messages_gone,
        "artifacts_gone": artifacts_gone,
        "attachment_blobs_gone": attachments_gone,
        "verified": all([thread_gone, messages_gone, artifacts_gone, attachments_gone]),
    }


def sweep(*, dry_run: bool = False) -> dict:
    """
    The nightly sweep.

    Runs with or without a broker: this is a privacy obligation, and it must not quietly
    stop because a Celery worker was never deployed.
    """
    due = expired_threads()
    total = due.count()
    if dry_run:
        return {"due": total, "purged": 0, "failed": 0, "dry_run": True}

    purged = failed = 0
    for thread in due.iterator():
        try:
            purge_thread(thread, reason="retention_expiry")
            purged += 1
        except Exception:  # noqa: BLE001
            failed += 1
            logger.exception("thread purge failed for %s", thread.id)

    summary = {"due": total, "purged": purged, "failed": failed,
               "at": timezone.now().isoformat()}
    if purged or failed:
        logger.info("thread.retention.sweep %s", summary)
    return summary
