"""XLSX extraction — sheet by sheet, values only."""

from __future__ import annotations

from io import BytesIO

from apps.attachments.services.handlers import ExtractionResult, metadata_only

MAX_ROWS_PER_SHEET = 2000


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    try:
        import openpyxl
    except ImportError:
        return metadata_only("xlsx", "xlsx reader unavailable")

    try:
        # read_only + data_only: we want VALUES, not formulas, and we must not evaluate
        # anything. data_only=True also avoids surfacing formula text as if it were data.
        workbook = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in workbook.worksheets:
            parts.append(f"[sheet: {sheet.title}]")
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index >= MAX_ROWS_PER_SHEET:
                    parts.append(f"[... {sheet.title} truncated at {MAX_ROWS_PER_SHEET} rows]")
                    break
                cells = [str(c) for c in row if c is not None]
                if cells:
                    parts.append(" | ".join(cells))
            if sum(len(p) for p in parts) > limit:
                break
        text = "\n".join(parts).strip()
        if not text:
            return metadata_only("xlsx", "no cell values")
        return ExtractionResult(text=text[:limit], handler="xlsx", truncated=len(text) > limit)
    except Exception as exc:  # noqa: BLE001
        return metadata_only("xlsx", f"unreadable: {exc}"[:200])
