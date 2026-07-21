"""
The attachment policy table (Backend v6.0 §4.2).

ONE TABLE, not scattered constants. Every size, count and type decision is here, so an
operator can read the whole policy in one place and a reviewer can see what changed.

── ACCEPTANCE (§19.7 rule 1) ────────────────────────────────────────────────
ANY file type and ANY number of files may be attached. There is NO user-facing count
limit. The limits below are SAFETY and ABUSE ceilings, and each returns a specific,
recoverable message rather than a silent failure.

The distinction is load-bearing. "You may attach at most 5 files" is a product limit and
would contradict R25. "That is more than we can accept in one session" is an abuse
ceiling, phrased so a real person hitting it accidentally is not treated as an attacker.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


def max_attachment_bytes() -> int:
    return int(getattr(settings, "MAX_ATTACHMENT_BYTES", 104_857_600))  # 100 MB


def max_attachment_bytes_per_turn() -> int:
    return int(getattr(settings, "MAX_ATTACHMENT_BYTES_PER_TURN", 524_288_000))  # 500 MB


def max_attachments_per_session() -> int:
    return int(getattr(settings, "MAX_ATTACHMENTS_PER_SESSION", 200))


def pre_nda_retention_days() -> int:
    return int(getattr(settings, "PRE_NDA_ATTACHMENT_RETENTION_DAYS", 30))


def post_nda_retention_days() -> int:
    """Post-NDA files follow the client's contractual retention; this is the default."""
    return int(getattr(settings, "ATTACHMENT_RETENTION_DAYS", 365))


# Extraction sandbox ceilings. A file that needs more than this is represented by
# metadata only — which is an honest outcome, not a failure.
def extraction_timeout_seconds() -> int:
    return int(getattr(settings, "ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS", 30))


def extraction_memory_mb() -> int:
    return int(getattr(settings, "ATTACHMENT_EXTRACTION_MEMORY_MB", 512))


def max_extracted_chars() -> int:
    return int(getattr(settings, "ATTACHMENT_MAX_EXTRACTED_CHARS", 400_000))


# Archive-bomb guards. A zip that expands 100x or nests 10 deep is not a document.
MAX_ARCHIVE_RATIO = 100
MAX_ARCHIVE_DEPTH = 8
MAX_ARCHIVE_ENTRIES = 10_000


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of one policy check, carrying the message the visitor will see."""

    allowed: bool
    reason: str = ""
    message: str = ""

    def __bool__(self) -> bool:
        return self.allowed


# ── The visitor-facing messages (Playbook §13.4) ─────────────────────────────
# Kept verbatim here so a reword is a deliberate edit in one place. Every one of them
# tells the visitor what they CAN still do — the message is never a dead end.
MSG_TOO_LARGE = (
    "This file is larger than we can accept. You can send the message without it, "
    "or attach a smaller version."
)
MSG_TURN_TOO_LARGE = (
    "Those files are larger than we can accept in one message together. "
    "You can send some of them now and the rest in a follow-up."
)
MSG_SESSION_CEILING = (
    "That is more files than we can accept in one session. "
    "You can send the message without them, or remove a few and try again."
)
MSG_COULD_NOT_PROCESS = (
    "We could not process this file safely, so we have not used it. "
    "You can send the message without it."
)
MSG_NOT_READABLE = (
    "Attached. We could not read the contents of this format, so we will work from "
    "what you tell us about it."
)
MSG_DELETED = "Removed. We have deleted this file and anything we read from it."


def check_file_size(size_bytes: int) -> PolicyDecision:
    limit = max_attachment_bytes()
    if size_bytes > limit:
        return PolicyDecision(False, "file_too_large", MSG_TOO_LARGE)
    return PolicyDecision(True)


def check_turn_total(total_bytes: int) -> PolicyDecision:
    limit = max_attachment_bytes_per_turn()
    if total_bytes > limit:
        return PolicyDecision(False, "turn_total_too_large", MSG_TURN_TOO_LARGE)
    return PolicyDecision(True)


def check_session_count(current_count: int, adding: int = 1) -> PolicyDecision:
    limit = max_attachments_per_session()
    if current_count + adding > limit:
        return PolicyDecision(False, "session_ceiling", MSG_SESSION_CEILING)
    return PolicyDecision(True)


def check_type(detected_mime: str, filename: str) -> PolicyDecision:
    """
    ANY type is accepted (§19.7 rule 1).

    This function exists so the acceptance rule has an explicit home rather than being
    an absence. Unsupported types are accepted and represented by metadata only — they
    are never rejected for being unfamiliar.
    """
    return PolicyDecision(True)


def retention_days_for(*, pre_nda: bool) -> int:
    return pre_nda_retention_days() if pre_nda else post_nda_retention_days()


def snapshot() -> dict:
    """The whole policy, for the cockpit and for tests."""
    return {
        "max_attachment_bytes": max_attachment_bytes(),
        "max_attachment_bytes_per_turn": max_attachment_bytes_per_turn(),
        "max_attachments_per_session": max_attachments_per_session(),
        "file_count_per_turn": "no product limit",
        "file_type": "any",
        "pre_nda_retention_days": pre_nda_retention_days(),
        "post_nda_retention_days": post_nda_retention_days(),
        "extraction_timeout_seconds": extraction_timeout_seconds(),
        "extraction_memory_mb": extraction_memory_mb(),
        "max_extracted_chars": max_extracted_chars(),
        "max_archive_ratio": MAX_ARCHIVE_RATIO,
        "max_archive_depth": MAX_ARCHIVE_DEPTH,
    }
