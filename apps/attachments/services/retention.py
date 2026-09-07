"""Attachment retention and verifiable purge."""

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
    """Delete canonical bytes first; never claim purge when provider deletion failed."""
    from apps.attachments import storage
    from apps.attachments.services import audit

    blob_removed = True
    if attachment.blob_key:
        blob_removed = storage.delete(attachment.blob_key)
        if not blob_removed:
            raise RuntimeError("attachment blob deletion failed; purge not recorded")

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
    return purge(attachment, reason="visitor_delete")


def expired():
    return Attachment.objects.filter(
        retention_expires_at__lt=timezone.now(), purged_at__isnull=True
    )


def sweep() -> dict:
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
    count = 0
    for attachment in Attachment.objects.filter(thread=thread, purged_at__isnull=True):
        purge(attachment, reason="thread_deleted")
        count += 1
    return count
