"""
Sandboxed extraction dispatch (Backend v6.0 §4.3, §19.7 rule 4).

    Extraction runs in an ISOLATED WORKER with NO NETWORK EGRESS, a memory and CPU
    ceiling, and a WALL-CLOCK TIMEOUT.

── THE GATE ────────────────────────────────────────────────────────────────
``run()`` REFUSES to extract without a clean ``AttachmentScan`` row. Scan strictly
precedes extraction, and "an extraction that runs on an unscanned blob is a defect with
a named test" (§4.3) — that test is
``tests/test_attachments/test_scan_before_extract.py``.

The refusal is checked against DATA, not against call order. Two functions called in the
right sequence today can be reordered tomorrow; a query that requires a clean row cannot.
"""

from __future__ import annotations

import logging
import time

from apps.attachments import policy
from apps.attachments.models import AttachmentExtraction, AttachmentStatus
from apps.attachments.services.handlers import ExtractionResult, metadata_only

logger = logging.getLogger("itrix")


class ScanRequired(Exception):
    """Raised when extraction is attempted before a clean scan exists."""


# detected mime -> handler module name.
_MIME_HANDLERS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "text",
    "text/csv": "csv_tsv",
    "application/json": "json_xml",
    "application/xml": "json_xml",
    "text/xml": "json_xml",
    "image/png": "image_ocr",
    "image/jpeg": "image_ocr",
    "image/gif": "image_ocr",
    "image/webp": "image_ocr",
}

_EXTENSION_HANDLERS = {
    ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx",
    ".csv": "csv_tsv", ".tsv": "csv_tsv",
    ".json": "json_xml", ".xml": "json_xml", ".yaml": "json_xml", ".yml": "json_xml",
    ".txt": "text", ".md": "text", ".log": "text", ".rst": "text", ".ini": "text",
    ".png": "image_ocr", ".jpg": "image_ocr", ".jpeg": "image_ocr", ".gif": "image_ocr",
}

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp", ".cc", ".java",
    ".go", ".rs", ".rb", ".php", ".sh", ".sql", ".f90", ".f", ".cu", ".m", ".jl",
    ".r", ".scala", ".kt", ".swift",
}


def handler_for(detected_mime: str, filename: str) -> str:
    """Choose a handler. Falls through to ``opaque``, which always succeeds."""
    lowered = (filename or "").lower()
    for extension in _CODE_EXTENSIONS:
        if lowered.endswith(extension):
            return "code"
    for extension, name in _EXTENSION_HANDLERS.items():
        if lowered.endswith(extension):
            return name
    return _MIME_HANDLERS.get((detected_mime or "").lower(), "opaque")


def run(attachment) -> AttachmentExtraction:
    """
    Extract text from one attachment.

    Raises ``ScanRequired`` when no clean scan exists. Everything else is caught and
    turned into a metadata-only result: extraction is the step most likely to fail on
    hostile input, and a crash here must not lose the visitor's turn.
    """
    from apps.attachments.services import scanner

    if not scanner.has_clean_scan(attachment):
        raise ScanRequired(
            f"Attachment {attachment.id} has no clean scan; refusing to extract."
        )

    attachment.status = AttachmentStatus.EXTRACTING
    attachment.save(update_fields=["status", "updated_at"])

    started = time.monotonic()
    handler_name = handler_for(attachment.detected_mime, attachment.filename)
    result = _dispatch(attachment, handler_name)
    duration_ms = int((time.monotonic() - started) * 1000)

    extraction, _created = AttachmentExtraction.objects.update_or_create(
        attachment=attachment,
        defaults={
            "handler": result.handler,
            "text": result.text or None,
            "page_count": result.page_count,
            "char_count": result.char_count,
            "truncated": result.truncated,
            "metadata_only": result.metadata_only,
            "error": result.error or "",
            "duration_ms": duration_ms,
        },
    )

    # READY covers metadata-only too. The file was accepted; that is the outcome.
    attachment.status = AttachmentStatus.READY
    if result.metadata_only:
        attachment.visitor_note = policy.MSG_NOT_READABLE
    attachment.save(update_fields=["status", "visitor_note", "updated_at"])

    logger.info(
        "attachment.extract %s handler=%s chars=%s metadata_only=%s in %sms",
        attachment.id, result.handler, result.char_count, result.metadata_only, duration_ms,
    )
    return extraction


def _dispatch(attachment, handler_name: str) -> ExtractionResult:
    """Run the handler in the sandbox, falling back to metadata-only on any failure."""
    from apps.attachments import storage

    try:
        data = storage.read(attachment.blob_key)
    except Exception as exc:  # noqa: BLE001
        return metadata_only(handler_name, f"could not read blob: {exc}"[:200])

    try:
        from workers.extraction_entrypoint import run_sandboxed

        return run_sandboxed(
            handler_name,
            data,
            filename=attachment.filename,
            limit=policy.max_extracted_chars(),
            timeout=policy.extraction_timeout_seconds(),
            memory_mb=policy.extraction_memory_mb(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("sandboxed extraction failed for %s", attachment.id)
        return metadata_only(handler_name, f"extraction failed: {exc}"[:200])
