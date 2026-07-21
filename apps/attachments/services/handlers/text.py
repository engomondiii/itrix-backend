"""Plain text, source code, JSON/XML, CSV/TSV — anything decodable as text."""

from __future__ import annotations

from apps.attachments.services.handlers import ExtractionResult

# Tried in order. utf-8 first because it is correct far more often than the others.
_ENCODINGS = ("utf-8", "utf-16", "latin-1")


def extract(data: bytes, *, filename: str = "", limit: int = 400_000) -> ExtractionResult:
    for encoding in _ENCODINGS:
        try:
            text = data.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        # Undecodable in every encoding we try — accepted, represented by metadata.
        return ExtractionResult(handler="text", metadata_only=True,
                                error="could not decode as text")

    truncated = len(text) > limit
    return ExtractionResult(
        text=text[:limit], handler=_handler_for(filename), truncated=truncated
    )


def _handler_for(filename: str) -> str:
    lowered = (filename or "").lower()
    if lowered.endswith((".json", ".xml", ".yaml", ".yml", ".toml")):
        return "json_xml"
    if lowered.endswith((".csv", ".tsv")):
        return "csv_tsv"
    if lowered.endswith(
        (".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp", ".cc",
         ".java", ".go", ".rs", ".rb", ".php", ".sh", ".sql", ".f90", ".f", ".cu",
         ".m", ".jl", ".r", ".scala", ".kt", ".swift")
    ):
        return "code"
    return "text"
