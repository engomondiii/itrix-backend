"""
Attachment intake (Backend v6.0 §4.3).

    intake.stage()  accept bytes, hash, store outside the web root, associate to a turn

── PRE-NDA IS DECIDED HERE, FROM THE PLANE ──────────────────────────────────
``pre_nda`` is set at upload from the THREAD's identity state — never from a request
parameter, never from a claim in the upload. That is what makes §19.7 rule 6 true:

    Uploading a document — INCLUDING ONE THAT IS ITSELF CONFIDENTIAL — does not identify
    the visitor, does not create a Client, and does not unlock nda_only content.

A visitor who uploads their architecture diagram has not proven anything about who they
are. The upload is evidence of trust, not of identity.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.attachments import policy, storage
from apps.attachments.models import Attachment, AttachmentStatus

logger = logging.getLogger("itrix")


class AttachmentRejected(Exception):
    """Raised when policy refuses a file. Carries the visitor-facing message."""

    def __init__(self, message: str, reason: str = ""):
        self.message = message
        self.reason = reason
        super().__init__(message)


@transaction.atomic
def stage(*, thread=None, filename: str, data: bytes, declared_mime: str = "",
          uploaded_by_kind: str = "session", uploaded_by_id: str = "") -> Attachment:
    """
    Accept one file.

    Raises ``AttachmentRejected`` on a policy breach — carrying the specific, recoverable
    message the visitor sees. A rejected FILE never rejects the TURN: the caller sends
    the message without it.

    ``thread`` MAY BE None (2026-08-13). A visitor attaches on the arrival screen before
    they have typed anything, so before a Thread exists. The file is staged against the
    UPLOADER — ``uploaded_by_id`` — and ``bind()`` attaches it to the thread the moment
    the first turn creates one. ``_is_pre_nda(None)`` returns True, so an unbound file
    gets the SHORTER retention and the stricter handling: the conservative direction for
    a document whose conversation we do not know yet.
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

    # pre_nda derives from the THREAD, not from the request.
    pre_nda = _is_pre_nda(thread)
    retention_days = policy.retention_days_for(pre_nda=pre_nda)

    blob_key = storage.new_blob_key(filename)
    written, sha256 = storage.write(blob_key, data or b"")

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

    logger.info(
        "attachment.stage %s thread=%s bytes=%s pre_nda=%s",
        attachment.id, getattr(thread, "id", None) or "unbound", written, pre_nda,
    )
    _audit(attachment, "upload")
    return attachment


def _is_pre_nda(thread) -> bool:
    """
    Pre-NDA unless the owning client has actually signed one.

    Defaults to TRUE. An unknown state gets the SHORTER retention and the stricter
    handling — the conservative direction for a document we may not have been meant to
    receive.
    """
    client = getattr(thread, "client", None)
    if client is None:
        return True
    return not bool(getattr(client, "nda_signed", False))


def check_turn_total(files: list[tuple[str, bytes]]) -> None:
    """Raise if the combined size of one turn's files exceeds the per-turn ceiling."""
    total = sum(len(data or b"") for _name, data in files)
    decision = policy.check_turn_total(total)
    if not decision:
        raise AttachmentRejected(decision.message, decision.reason)


class AttachmentAlreadyBound(Exception):
    """Raised when a caller tries to move an attachment onto a second thread."""


def bind(attachment, thread) -> Attachment:
    """
    Attach a staged, UNBOUND attachment to the thread it was sent with.

    ── WHY THIS REFUSES A RE-BIND RATHER THAN ALLOWING ONE ──────────────────────
    Boundary 3 says an attachment is scoped to its thread. If this function accepted a
    thread for an attachment that already had one, then a caller who knew (or guessed) an
    attachment id could name it in their own ``POST threads/`` and carry somebody else's
    document into their own conversation, where the excerpt selector would feed it to the
    model. Ownership is checked by the caller; the CARDINALITY is checked here, so the
    boundary does not depend on every call site remembering it.

    Re-binding to the SAME thread is a no-op rather than an error: a retried turn submit
    must be safe to replay.

    Rebinding also re-derives ``pre_nda`` and the retention window from the thread. An
    unbound file was staged with the conservative pre-NDA default; once the thread is
    known, the real identity state decides — and it can only ever be read from the
    thread, never from the request.
    """
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
    """
    Bind every attachment in ``attachment_ids`` that this uploader actually owns.

    Returns the ids that are now on ``thread`` — bound here, or already there.

    UNKNOWN, FOREIGN AND ALREADY-BOUND IDS ARE SKIPPED, NOT RAISED. The visitor's words
    are already on the record by the time this runs; a bad id in the list must never cost
    them the sentence they typed. What it costs is that file, and the count of what was
    linked is returned so the caller can report it.
    """
    if not attachment_ids:
        return []

    wanted = [str(a) for a in attachment_ids if a]
    if not wanted:
        return []

    rows = Attachment.objects.filter(id__in=wanted, deleted_at__isnull=True)
    if uploaded_by_id:
        # The upload recorded WHO staged it. Without this filter, naming a stranger's
        # unbound attachment id would bind their document into this thread.
        rows = rows.filter(uploaded_by_id=str(uploaded_by_id))

    bound: list[str] = []
    for attachment in rows:
        try:
            bind(attachment, thread)
        except AttachmentAlreadyBound:
            logger.info(
                "attachment.bind refused %s (already on thread %s)",
                attachment.id, attachment.thread_id,
            )
            continue
        bound.append(str(attachment.id))
    return bound


def associate(attachment, message) -> None:
    """Link a staged attachment to the turn it was sent with."""
    from apps.conversations.models import MessageAttachment

    MessageAttachment.objects.get_or_create(
        message=message,
        attachment_id=str(attachment.id),
        defaults={"order": 0},
    )


def process(attachment) -> Attachment:
    """
    Run the full pipeline for one attachment: scan -> extract -> excerpt.

    Scan strictly precedes extraction; a quarantined file stops here and is never handed
    to a parser.
    """
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
