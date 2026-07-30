"""
THE ATTACHMENT REVIEW QUEUE, and RELEASE WITH A REASON (Backend v7.1 Phase 2).

``analytics/attachments/`` answers "how many files, of what types, how often quarantined?".
This answers "which file is waiting for a human, and what did the scanner say about it?".

── RELEASING A QUARANTINED FILE REQUIRES A WRITTEN REASON ──────────────────

Not a confirmation dialog. A REASON, stored, attributed, and permanent.

The scanner quarantined the file because something about it matched. An operator releasing
it is overruling that — which is a legitimate thing to do (scanners produce false
positives, and a customer's real architecture diagram should not be lost to one) and is
also the single most dangerous action available on this surface. It takes a file the system
decided was unsafe and makes it readable by the extraction pipeline.

So the reason is required at the API level, not the UI level. A UI-only requirement is a
requirement that disappears the moment anyone calls the endpoint directly, and the whole
value of the reason is that it exists later, when someone asks why a malicious file was
processed.

── AND THE AUDIT ROW IS WRITTEN IN THE SAME TRANSACTION AS THE RELEASE ─────
A release whose audit row failed to write is a release nobody can account for. They land
together or neither lands — which is the same reasoning the assent record uses, and for the
same reason: the record is what makes the action defensible.

── WHAT A RELEASE DOES NOT DO ──────────────────────────────────────────────
It does not raise the file's disclosure level, and it cannot. An attachment's level is
capped by the plane that uploaded it and a release does not touch it (§19.7 rule 4). A
released file is a file the pipeline may now READ; it is not a file that has become more
shareable.
"""

from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger("itrix")

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# The minimum a reason has to be to be worth storing. Short enough not to be a hurdle,
# long enough that "ok" and "." do not pass — those are a click, not a reason.
MIN_REASON_CHARS = 12


class ReleaseRefused(Exception):
    """Raised when a release is attempted without an adequate reason."""


def _needs_review(status: str) -> bool:
    """Quarantined or failed. Both are files a human has to decide about."""
    return status in {"quarantined", "failed"}


def rows(*, limit: int = DEFAULT_LIMIT, include_resolved: bool = False) -> list[dict]:
    """
    Files waiting on a human, oldest first.

    OLDEST FIRST, unlike every other queue in the cockpit. A quarantined attachment is a
    visitor's document sitting in limbo: they uploaded it, the surface told them it is being
    checked, and nothing has happened since. Newest-first ordering would leave the oldest
    file waiting indefinitely, which is the one outcome the visitor experiences directly.
    """
    from apps.attachments.models import Attachment, AttachmentStatus

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    qs = Attachment.objects.filter(deleted_at__isnull=True, purged_at__isnull=True)
    if not include_resolved:
        qs = qs.filter(
            status__in=[AttachmentStatus.QUARANTINED, AttachmentStatus.FAILED]
        )

    out: list[dict] = []
    for att in qs.select_related("thread").order_by("created_at")[:limit]:
        scan = att.scans.order_by("-scanned_at").first()
        out.append(
            {
                "attachmentId": str(att.id),
                "threadId": str(att.thread_id) if att.thread_id else None,
                "filename": att.filename or "",
                # BOTH mimes. A declared/detected mismatch is itself a signal, and showing
                # only one hides it.
                "declaredMime": att.declared_mime or "",
                "detectedMime": att.detected_mime or "",
                "bytes": att.bytes or 0,
                "status": att.status,
                "riskFlags": att.risk_flags or [],
                # Pre-NDA files carry shortened retention and restricted handling. An
                # operator releasing one should know that before they do.
                "preNda": bool(att.pre_nda),
                "retentionExpiresAt": (
                    att.retention_expires_at.isoformat() if att.retention_expires_at else None
                ),
                "scanVerdict": getattr(scan, "verdict", "") or "",
                # WHY the scanner objected. Without this the operator is being asked to
                # overrule a decision whose grounds they cannot see.
                "scanDetail": (getattr(scan, "detail", "") or "")[:500],
                "scannedAt": scan.scanned_at.isoformat() if scan else None,
                "uploadedByKind": att.uploaded_by_kind or "",
                "visitorNote": (att.visitor_note or "")[:300],
                "createdAt": att.created_at.isoformat(),
                "needsReview": _needs_review(att.status),
            }
        )
    return out


def detail(attachment_id: str) -> dict | None:
    """
    One file, with its full scan history and its audit trail.

    The audit trail is the point of this view. Every read, download, release and purge is a
    row, and they survive the attachment being purged — a purge that erased its own audit
    trail would make the retention guarantee unverifiable, which is the same as not having
    one.
    """
    from apps.attachments.models import Attachment

    att = (
        Attachment.objects.select_related("thread")
        .filter(id=attachment_id)
        .first()
    )
    if att is None:
        return None

    base = rows(limit=1, include_resolved=True)
    row = next((r for r in base if r["attachmentId"] == str(att.id)), None)
    if row is None:
        # Not in the first page of the queue; build the row directly rather than paging.
        row = {"attachmentId": str(att.id), "filename": att.filename or "", "status": att.status}

    scans = [
        {
            "engine": s.engine,
            "verdict": s.verdict,
            "detail": (s.detail or "")[:500],
            "scannedAt": s.scanned_at.isoformat(),
        }
        for s in att.scans.order_by("-scanned_at")[:20]
    ]

    audit = [
        {
            "action": a.action,
            "plane": a.plane,
            "subject": a.subject,
            "purpose": a.purpose,
            "detail": a.detail,
            "at": a.created_at.isoformat(),
        }
        for a in att.audit_entries.order_by("-created_at")[:100]
    ]

    return {**row, "scans": scans, "audit": audit}


def release(attachment_id: str, *, user, reason: str) -> dict:
    """
    Release a quarantined file for extraction. REQUIRES A REASON.

    ── THE REASON IS ENFORCED HERE, NOT IN THE UI ──────────────────────────
    A UI-only requirement disappears the moment anyone calls the endpoint directly, and the
    entire value of the reason is that it exists LATER — when someone asks why a file the
    scanner objected to was processed. So a short or empty reason raises.

    ── THE AUDIT ROW AND THE STATUS CHANGE ARE ONE TRANSACTION ─────────────
    A release whose audit row failed to write is a release nobody can account for. They land
    together or neither lands.

    ── AND IT DOES NOT RAISE THE FILE'S DISCLOSURE LEVEL ───────────────────
    An attachment's level is capped by the plane that uploaded it and cannot be raised by
    anything (§19.7 rule 4). A released file is one the pipeline may now READ. It has not
    become more shareable, and this function has no code path that could make it so.
    """
    from apps.attachments.models import Attachment, AttachmentStatus

    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_CHARS:
        raise ReleaseRefused(
            "Releasing a quarantined file requires a written reason of at least "
            f"{MIN_REASON_CHARS} characters. The scanner objected to this file; the reason "
            "is what makes overruling it accountable."
        )

    with transaction.atomic():
        att = Attachment.objects.select_for_update().filter(id=attachment_id).first()
        if att is None:
            raise ReleaseRefused("No such attachment.")

        if att.deleted_at or att.purged_at:
            # A visitor deleted it, or retention purged it. Releasing it would resurrect
            # something the platform promised was gone.
            raise ReleaseRefused(
                "That attachment has been deleted or purged. It cannot be released."
            )

        if att.status != AttachmentStatus.QUARANTINED:
            raise ReleaseRefused(
                f"Only a quarantined attachment can be released; this one is '{att.status}'."
            )

        previous = att.status
        # Back to `scanned`: the file is now eligible for extraction. NOT `ready` — that
        # would claim extraction had happened, and the pipeline still has to run.
        att.status = AttachmentStatus.SCANNED
        att.save(update_fields=["status", "updated_at"])

        # Same transaction. The record is what makes the action defensible.
        from apps.attachments.models import AttachmentAuditEntry

        AttachmentAuditEntry.objects.create(
            attachment=att,
            action="release",
            plane="team",
            subject=str(getattr(user, "email", "") or getattr(user, "id", "") or "unknown"),
            purpose=cleaned[:300],
            detail=f"released from {previous} by {getattr(user, 'role', '') or 'team'}",
        )

    logger.warning(
        "attachment.released id=%s by=%s reason=%r",
        attachment_id,
        getattr(user, "email", "?"),
        cleaned[:120],
    )
    return {"attachmentId": str(att.id), "status": att.status, "released": True}


def quarantine(attachment_id: str, *, user, reason: str) -> dict:
    """
    Quarantine a file a human judged unsafe, whatever the scanner said.

    The inverse of ``release``, and it requires a reason for the SAME reason: an operator
    quarantining a customer's document is withholding something the customer sent, and the
    customer may ask why.

    Tightening is always permitted. Unlike ``release``, this works from any state — a file
    already extracted can still be quarantined if a human notices something the scanner did
    not.
    """
    from apps.attachments.models import Attachment, AttachmentAuditEntry, AttachmentStatus

    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_CHARS:
        raise ReleaseRefused(
            "Quarantining a file requires a written reason of at least "
            f"{MIN_REASON_CHARS} characters. The customer sent this document and may ask why "
            "it was withheld."
        )

    with transaction.atomic():
        att = Attachment.objects.select_for_update().filter(id=attachment_id).first()
        if att is None:
            raise ReleaseRefused("No such attachment.")
        if att.purged_at:
            raise ReleaseRefused("That attachment has been purged.")

        previous = att.status
        att.status = AttachmentStatus.QUARANTINED
        att.save(update_fields=["status", "updated_at"])

        AttachmentAuditEntry.objects.create(
            attachment=att,
            action="quarantine",
            plane="team",
            subject=str(getattr(user, "email", "") or getattr(user, "id", "") or "unknown"),
            purpose=cleaned[:300],
            detail=f"quarantined from {previous} by {getattr(user, 'role', '') or 'team'}",
        )

    return {"attachmentId": str(att.id), "status": att.status, "quarantined": True}


def summary() -> dict:
    """The counts above the queue."""
    from apps.attachments.models import Attachment, AttachmentStatus

    live = Attachment.objects.filter(deleted_at__isnull=True, purged_at__isnull=True)
    return {
        "quarantined": live.filter(status=AttachmentStatus.QUARANTINED).count(),
        "failed": live.filter(status=AttachmentStatus.FAILED).count(),
        # Pre-NDA files in the queue are the urgent ones: shortened retention means they can
        # expire while waiting for a decision, and a file that expired unreviewed is a
        # decision made by a timer.
        "preNdaAwaitingReview": live.filter(
            status__in=[AttachmentStatus.QUARANTINED, AttachmentStatus.FAILED], pre_nda=True
        ).count(),
    }
