"""
Relevance selection for the context budget (Backend v6.0 §4.3, Architecture §12.5).

    Attachment excerpts are selected by RELEVANCE TO THE CURRENT TURN, not by file order.

── WHY NOT JUST SEND THE WHOLE DOCUMENT ─────────────────────────────────────
Attachment content enters the context at PRIORITY 5 — below the visitor's own current
turn (§2.4). A 200-page PDF sent whole would consume the budget and push out the question
being asked. Selecting excerpts is what lets a large upload inform an answer instead of
replacing it.

Scoring is deterministic keyword overlap, not an embedding call. Two reasons: an
embedding call on every turn is a latency and cost tax on the hot path, and a
deterministic selection is reproducible when someone asks why a particular passage was
used.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("itrix")

DEFAULT_EXCERPT_CHARS = 1500
DEFAULT_MAX_EXCERPTS = 6

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "on", "for", "with", "as", "at", "by", "it", "this", "that",
    "we", "our", "you", "your", "i", "they", "their", "from", "has", "have", "had",
    "do", "does", "did", "can", "could", "would", "should", "will", "not", "no",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _windows(text: str, size: int) -> list[str]:
    """
    Split into overlapping windows on paragraph boundaries where possible.

    Overlap matters: a passage that straddles a boundary would otherwise be split so
    that neither half scores well enough to be selected.
    """
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    windows: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            windows.append(current)
        if len(paragraph) <= size:
            current = paragraph
        else:
            for start in range(0, len(paragraph), size):
                windows.append(paragraph[start:start + size])
            current = ""
    if current:
        windows.append(current)
    return windows


def select(text: str, query: str, *, max_excerpts: int = DEFAULT_MAX_EXCERPTS,
           excerpt_chars: int = DEFAULT_EXCERPT_CHARS) -> list[str]:
    """
    The passages most relevant to ``query``.

    With no query, returns the OPENING of the document — the first pages of a technical
    document are usually its summary, which is a better default than an arbitrary middle.
    """
    if not (text or "").strip():
        return []

    windows = _windows(text, excerpt_chars)
    if not windows:
        return []
    if not (query or "").strip():
        return windows[:max_excerpts]

    query_tokens = _tokens(query)
    if not query_tokens:
        return windows[:max_excerpts]

    scored: list[tuple[float, int, str]] = []
    for index, window in enumerate(windows):
        window_tokens = _tokens(window)
        if not window_tokens:
            continue
        overlap = len(query_tokens & window_tokens)
        if not overlap:
            continue
        # Normalise by window size so a long window does not win on length alone.
        score = overlap / (len(window_tokens) ** 0.5)
        scored.append((score, index, window))

    if not scored:
        return windows[:max_excerpts]

    scored.sort(key=lambda row: (-row[0], row[1]))
    chosen = scored[:max_excerpts]
    # Restore DOCUMENT ORDER for the selected windows — a reader (human or model)
    # follows an argument better in the order it was written.
    chosen.sort(key=lambda row: row[1])
    return [window for _score, _index, window in chosen]


def build(attachment, query: str = "") -> list:
    """Build and persist excerpts for one attachment."""
    from apps.attachments.models import AttachmentExcerpt

    extraction = getattr(attachment, "extraction", None)
    if extraction is None or not extraction.has_text:
        return []

    AttachmentExcerpt.objects.filter(attachment=attachment).delete()
    rows = []
    for ordinal, text in enumerate(select(extraction.text, query)):
        rows.append(
            AttachmentExcerpt(
                attachment=attachment, ordinal=ordinal, text=text, char_count=len(text)
            )
        )
    if rows:
        AttachmentExcerpt.objects.bulk_create(rows)
    return rows


def for_context(thread, query: str = "", *, max_attachments: int = 10) -> list[dict]:
    """
    Fenced excerpts for every readable attachment on a thread.

    Returns dicts ready for ``fencing.fence_many``. A metadata-only attachment is
    INCLUDED — the model should know the file exists and that we could not read it,
    rather than being left to assume nothing was uploaded.
    """
    from apps.attachments.models import Attachment, AttachmentStatus

    attachments = Attachment.objects.filter(
        thread=thread, status=AttachmentStatus.READY, deleted_at__isnull=True
    ).select_related("extraction")[:max_attachments]

    out: list[dict] = []
    for attachment in attachments:
        extraction = getattr(attachment, "extraction", None)
        if extraction is None:
            continue
        if extraction.metadata_only or not extraction.has_text:
            out.append({
                "filename": attachment.filename,
                "handler": extraction.handler,
                "metadata_only": True,
                "text": "",
            })
            continue
        chosen = select(extraction.text, query)
        out.append({
            "filename": attachment.filename,
            "handler": extraction.handler,
            "metadata_only": False,
            "text": "\n\n[...]\n\n".join(chosen),
        })
    return out
