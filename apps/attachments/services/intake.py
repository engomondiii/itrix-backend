"""Attachment intake and scan-before-extract processing."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.attachments import policy, storage
from apps.attachments.models import Attachment, AttachmentStatus

logger = logging.getLogger("itrix")


class AttachmentRejected(Exception):
    def __init__(self, message: str, reason: str = ""):
        self.message = message
        self.reason = reason
        super().__init__(message)


@transaction.atomic
def stage(
    *,
    thread=None,
    filename: str,
    data: bytes,
    declared_mime: str = "",
    uploaded_by_kind: str = "session",
    uploaded_by_id: str = "",
) -> Attachment:
    """Persist private bytes and their DB row as one logical operation.

    Object stores are outside the database transaction. If the object write succeeds but
    the DB insert fails, delete the object immediately before re-raising so confidential
    orphan blobs are not left behind.
    """
    size = len(data or b"")
    decision = policy.check_file_size(size)
    if not decision:
        raise AttachmentRejected(decision.message, decision.reason)

    if uploaded_by_id:
        existing = Attachment.objects.filter(
            uploaded_by_id=uploaded_by_id, deleted_at__isnull=True
        ).count()
        decision = policy.check_session_count(existing)
        if not decision:
            raise AttachmentRejected(decision.message, decision.reason)

    pre_nda = _is_pre_nda(thread)
    retention_days = policy.retention_days_for(pre_nda=pre_nda)
    blob_key = storage.new_blob_key(filename)
    written, sha256 = storage.write(blob_key, data or b"")

    try:
        attachment = Attachment.objects.create(
            thread=thread,
            uploaded_by_kind=uploaded_by_kind,
            uploaded_by_id=str(uploaded_by_id or "")[:128],
            filename=(filename or "unnamed")[:512],
            declared_mime=(declared_mime or "")[:200],
            bytes=written,
            sha256=sha256,
            blob_key=blob_key,
            status=AttachmentStatus.STAGED,
            pre_nda=pre_nda,
            retention_expires_at=timezone.now() + timezone.timedelta(days=retention_days),
        )
    except Exception:  # noqa: BLE001
        if not storage.delete(blob_key):
            logger.critical("attachment orphan cleanup failed for blob %s", blob_key)
        raise

    logger.info(
        "attachment.stage %s thread=%s bytes=%s pre_nda=%s",
        attachment.id,
        getattr(thread, "id", None) or "unbound",
        written,
        pre_nda,
    )
    _audit(attachment, "upload")
    return attachment


def _is_pre_nda(thread) -> bool:
    client = getattr(thread, "client", None)
    if client is None:
        return True
    return not bool(getattr(client, "nda_signed", False))


def check_turn_total(files: list[tuple[str, bytes]]) -> None:
    total = sum(len(data or b"") for _name, data in files)
    decision = policy.check_turn_total(total)
    if not decision:
        raise AttachmentRejected(decision.message, decision.reason)


class AttachmentAlreadyBound(Exception):
    pass


def bind(attachment, thread) -> Attachment:
    """Bind an unbound attachment once; replaying the same binding is idempotent."""
    if attachment.thread_id is not None:
        if str(attachment.thread_id) == str(getattr(thread, "id", "")):
            return attachment
        raise AttachmentAlreadyBound(
            f"attachment {attachment.id} is already bound to thread {attachment.thread_id}"
        )

    pre_nda = _is_pre_nda(thread)
    attachment.thread = thread
    attachment.pre_nda = pre_nda
    attachment.retention_expires_at = timezone.now() + timezone.timedelta(
        days=policy.retention_days_for(pre_nda=pre_nda)
    )
    attachment.save(update_fields=["thread", "pre_nda", "retention_expires_at", "updated_at"])
    logger.info("attachment.bind %s -> thread=%s pre_nda=%s", attachment.id, thread.id, pre_nda)
    return attachment


def bind_many(attachment_ids, thread, *, uploaded_by_id: str = "") -> list[str]:
    if not attachment_ids:
        return []
    wanted = [str(value) for value in attachment_ids if value]
    if not wanted:
        return []
    rows = Attachment.objects.filter(id__in=wanted, deleted_at__isnull=True)
    if uploaded_by_id:
        rows = rows.filter(uploaded_by_id=str(uploaded_by_id))
    bound: list[str] = []
    for attachment in rows:
        try:
            bind(attachment, thread)
        except AttachmentAlreadyBound:
            logger.info(
                "attachment.bind refused %s (already on thread %s)",
                attachment.id,
                attachment.thread_id,
            )
            continue
        bound.append(str(attachment.id))
    return bound


def associate(attachment, message) -> None:
    from apps.conversations.models import MessageAttachment

    MessageAttachment.objects.get_or_create(
        message=message,
        attachment_id=str(attachment.id),
        defaults={"order": 0},
    )


def process(attachment) -> Attachment:
    """Strict pipeline: scan -> clean gate -> extraction -> excerpts."""
    from apps.attachments.services import excerpts, extractor, scanner

    scan_record = scanner.scan(attachment)
    attachment.refresh_from_db()
    if not scan_record.is_clean:
        logger.warning(
            "attachment.quarantined %s verdict=%s", attachment.id, scan_record.verdict
        )
        _audit(attachment, "quarantine", detail=scan_record.verdict)
        return attachment

    try:
        extractor.run(attachment)
    except extractor.ScanRequired:
        logger.exception("extraction refused for %s (no clean scan)", attachment.id)
        return attachment

    attachment.refresh_from_db()
    try:
        excerpts.build(attachment)
    except Exception:  # noqa: BLE001
        logger.exception("excerpt build failed for %s", attachment.id)
    _audit(attachment, "extract")
    return attachment


def _audit(attachment, action: str, detail: str = "") -> None:
    from apps.attachments.services import audit

    audit.record(attachment, action=action, detail=detail)
