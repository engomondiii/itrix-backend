"""PDF text extraction."""

from __future__ import annotations

from io import BytesIO

from apps.attachments.services.handlers import ExtractionResult, metadata_only


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError:
        return metadata_only("pdf", "pdf reader unavailable")

    try:
        reader = PdfReader(BytesIO(data))
        # An encrypted PDF is not a failure — it is a file we accepted and cannot read.
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return metadata_only("pdf", "encrypted")

        parts: list[str] = []
        total = 0
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                continue
            parts.append(text)
            total += len(text)
            if total >= limit:
                return ExtractionResult(
                    text="\n\n".join(parts)[:limit],
                    page_count=len(reader.pages),
                    handler="pdf",
                    truncated=True,
                )
        joined = "\n\n".join(parts).strip()
        if not joined:
            # A scanned PDF with no text layer. OCR is a separate handler.
            return metadata_only("pdf", "no extractable text layer")
        return ExtractionResult(text=joined, page_count=len(reader.pages), handler="pdf")
    except Exception as exc:  # noqa: BLE001
        return metadata_only("pdf", f"unreadable: {exc}"[:200])
