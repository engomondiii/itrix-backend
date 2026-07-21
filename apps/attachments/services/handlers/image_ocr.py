"""
Image OCR.

OCR is OPTIONAL and frequently unavailable. When it is, an image is accepted and
represented by metadata only — which is the honest outcome, and explicitly not a failure
(§13.4). We never tell a visitor their screenshot "failed".
"""

from __future__ import annotations

from io import BytesIO

from apps.attachments.services.handlers import ExtractionResult, metadata_only


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return metadata_only("image_ocr", "OCR not available in this deployment")

    try:
        image = Image.open(BytesIO(data))
        text = (pytesseract.image_to_string(image) or "").strip()
        if not text:
            return metadata_only("image_ocr", "no text found in image")
        return ExtractionResult(text=text[:limit], handler="image_ocr",
                                truncated=len(text) > limit)
    except Exception as exc:  # noqa: BLE001
        return metadata_only("image_ocr", f"OCR failed: {exc}"[:200])
