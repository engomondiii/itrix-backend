"""
Per-format extraction handlers (Backend v6.0 §4.3).

Each handler takes bytes and returns ``ExtractionResult``. None of them raises: an
unreadable file is a RESULT (``metadata_only=True``), not an exception, because §13.4 of
the Playbook forbids calling an accepted file a failure.

Every handler runs inside the sandbox (``workers/extraction_entrypoint.py``): no network
egress, a memory ceiling, and a wall-clock timeout.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExtractionResult:
    """What a handler produces. ``metadata_only`` is a success, not a failure."""

    text: str = ""
    page_count: int = 0
    handler: str = "opaque"
    truncated: bool = False
    metadata_only: bool = False
    error: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text or "")


def metadata_only(handler: str, reason: str = "") -> ExtractionResult:
    """The honest outcome for a format we cannot read."""
    return ExtractionResult(handler=handler, metadata_only=True, error=reason)
