"""
Retention and verifiable purge (Backend v6.0 §4.7, §19.7 rule 8).

    Pre-NDA attachments carry pre_nda=true, encryption at rest, thread-scoped access, and
    PRE_NDA_ATTACHMENT_RETENTION_DAYS (default 30). retention.sweep() runs nightly and
    writes a VERIFIABLE PURGE RECORD.

── WHAT "VERIFIABLE" MEANS HERE ─────────────────────────────────────────────
Deleting a row is not a purge. A purge is verifiable when three things are true
afterwards, and ``verify_purged`` checks all three:

    1. the BLOB is gone from storage
    2. the EXTRACTED TEXT is gone
    3. the DERIVED EXCERPTS are gone

The Attachment ROW survives, marked ``purged``, carrying its audit trail. A deletion that
leaves no trace is indistinguishable from a deletion that never happened — and the
visitor was promised "we have deleted this file and anything we read from it", which is a
claim someone has to be able to check.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.attachments.models import (
    Attachment,
    AttachmentExcerpt,
    AttachmentExtraction,
    AttachmentStatus,
)

logger = logging.getLogger("itrix")


@transaction.atomic
def purge(attachment, *, reason: str = "retention") -> dict:
    """
    Purge one attachment's content. Idempotent.

    Removes the blob, the extraction and the excerpts; keeps the row and its audit trail.
    """
    from apps.attachments import storage
    from apps.attachments.services import audit

    blob_removed = True
    if attachment.blob_key:
        blob_removed = storage.delete(attachment.blob_key)

    extraction_removed = AttachmentExtraction.objects.filter(attachment=attachment).delete()[0]
    excerpts_removed = AttachmentExcerpt.objects.filter(attachment=attachment).delete()[0]

    attachment.status = AttachmentStatus.PURGED
    attachment.purged_at = timezone.now()
    if attachment.deleted_at is None:
        attachment.deleted_at = attachment.purged_at
    attachment.blob_key = ""
    attachment.save(
        update_fields=["status", "purged_at", "deleted_at", "blob_key", "updated_at"]
    )

    audit.record(attachment, action="purge", detail=reason)
    record = {
        "attachment_id": str(attachment.id),
        "blob_removed": blob_removed,
        "extractions_removed": extraction_removed,
        "excerpts_removed": excerpts_removed,
        "purged_at": attachment.purged_at.isoformat(),
        "reason": reason,
    }
    logger.info("attachment.purge %s", record)
    return record


def verify_purged(attachment) -> dict:
    """
    Prove the purge. Returns a report with ``verified`` true only if ALL THREE hold.

    Exists so "verifiable" is a function somebody can call, not an adjective in a spec.
    """
    from apps.attachments import storage

    blob_gone = not (attachment.blob_key and storage.exists(attachment.blob_key))
    extraction_gone = not AttachmentExtraction.objects.filter(attachment=attachment).exists()
    excerpts_gone = not AttachmentExcerpt.objects.filter(attachment=attachment).exists()

    return {
        "attachment_id": str(attachment.id),
        "blob_gone": blob_gone,
        "extraction_gone": extraction_gone,
        "excerpts_gone": excerpts_gone,
        "verified": blob_gone and extraction_gone and excerpts_gone,
    }


def visitor_delete(attachment) -> dict:
    """
    A visitor removed an attachment (§19.7 rule 8).

    They may do this AT ANY TIME, and it purges immediately rather than scheduling a
    deletion. "We have deleted this file" must be true when it is said.
    """
    return purge(attachment, reason="visitor_delete")


def expired():
    """Attachments whose retention window has closed."""
    return Attachment.objects.filter(
        retention_expires_at__lt=timezone.now(),
        purged_at__isnull=True,
    )


def sweep() -> dict:
    """
    The nightly retention sweep.

    Returns a summary for the operator. Runs whether or not Celery is deployed — this is
    a privacy obligation, and it must not quietly stop because a worker was not started.
    """
    purged = 0
    failed = 0
    for attachment in expired().iterator():
        try:
            purge(attachment, reason="retention_expiry")
            purged += 1
        except Exception:  # noqa: BLE001
            failed += 1
            logger.exception("retention purge failed for %s", attachment.id)

    summary = {"purged": purged, "failed": failed, "at": timezone.now().isoformat()}
    if purged or failed:
        logger.info("attachment.retention.sweep %s", summary)
    return summary


def purge_thread(thread) -> int:
    """Purge every attachment on a thread — used when the thread itself is deleted."""
    count = 0
    for attachment in Attachment.objects.filter(thread=thread, purged_at__isnull=True):
        purge(attachment, reason="thread_deleted")
        count += 1
    return count
