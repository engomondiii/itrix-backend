"""csv_tsv extraction — delegates to the text handler, which already decodes safely."""

from __future__ import annotations

from apps.attachments.services.handlers import ExtractionResult
from apps.attachments.services.handlers import text as _text


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    result = _text.extract(data, filename=filename, limit=limit)
    if not result.metadata_only:
        result.handler = "csv_tsv"
    return result
