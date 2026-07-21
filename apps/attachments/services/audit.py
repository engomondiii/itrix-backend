"""
The attachment audit trail (Backend v6.0 §4.3, §19.7 rule 9).

    Every UPLOAD, SCAN RESULT, EXTRACTION OUTCOME, AGENT READ and DOWNLOAD is written to
    the audit log with the SUBJECT, the PLANE and the PURPOSE.

── WHY AGENT READS ARE AUDITED TOO ──────────────────────────────────────────
Downloads are the obvious thing to log. Agent reads are the easy thing to forget — and
they are the higher-volume path. Without them, "who saw this customer's pre-NDA
architecture document?" has an answer that is confidently wrong.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

ACTIONS = (
    "upload", "scan", "extract", "quarantine", "release",
    "agent_read", "download", "delete", "purge",
)


def record(attachment, *, action: str, plane: str = "", subject: str = "",
           purpose: str = "", detail: str = "") -> None:
    """
    Write one audit entry.

    Best-effort persistence, but ALWAYS logged. If the audit table is unavailable the
    line still reaches the log — losing the row must not mean losing the record.
    """
    entry = {
        "attachment_id": str(getattr(attachment, "id", "")),
        "thread_id": str(getattr(attachment, "thread_id", "")),
        "filename": getattr(attachment, "filename", ""),
        "action": action,
        "plane": plane,
        "subject": subject,
        "purpose": purpose,
        "detail": detail,
        "pre_nda": bool(getattr(attachment, "pre_nda", False)),
    }
    logger.info("attachment.audit %s", entry)

    try:
        from apps.governance.models import StreamGuardHit  # noqa: F401

        from apps.attachments.models import AttachmentAuditEntry

        AttachmentAuditEntry.objects.create(
            attachment=attachment,
            action=action,
            plane=plane,
            subject=subject,
            purpose=purpose,
            detail=detail,
        )
    except Exception:  # noqa: BLE001
        pass


def record_agent_read(attachment, *, agent_key: str, thread_id: str = "") -> None:
    """An agent used this attachment's content to answer a turn."""
    record(
        attachment,
        action="agent_read",
        plane="agent",
        subject=agent_key,
        purpose=f"context for thread {thread_id or attachment.thread_id}",
    )


def record_download(attachment, *, plane: str, subject: str, purpose: str = "") -> None:
    """
    Someone fetched the bytes.

    The cockpit tells the operator this is audited BEFORE the download starts (Surface 2
    v5.0 §4.2) — a log nobody knows about does not change behaviour.
    """
    record(attachment, action="download", plane=plane, subject=subject,
           purpose=purpose or "operator download")
