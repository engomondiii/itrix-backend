"""
The opaque handler — the honest fallback.

    Unsupported or opaque binaries are accepted, stored, and represented to the agent by
    METADATA ONLY (filename, type, size) — the visitor is told this plainly rather than
    being told the upload failed. (§19.7 rule 4)

This handler exists so that "we accept any format" is literally true. Every file reaches
a handler; the ones we cannot read reach this one.
"""

from __future__ import annotations

from apps.attachments.services.handlers import ExtractionResult


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    return ExtractionResult(
        handler="opaque",
        metadata_only=True,
        error="",  # NOT an error. The file was accepted; we simply cannot read it.
    )
