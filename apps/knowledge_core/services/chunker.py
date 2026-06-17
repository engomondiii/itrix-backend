"""
Chunker.

Splits a document's text into retrieval-sized chunks, preferring heading boundaries
(Markdown ``#`` markers, which the loader emits for docx headings too). Oversized
sections are further split on paragraph/sentence boundaries with a soft target size, so
no single chunk is too large to embed well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Soft targets (characters, not tokens — cheap and good enough for chunking).
TARGET_CHARS = 1200
MAX_CHARS = 2000
MIN_CHARS = 80

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass
class Chunk:
    index: int
    heading: str
    text: str

    @property
    def token_estimate(self) -> int:
        # ~4 chars per token is a reasonable rough estimate.
        return max(1, len(self.text) // 4)


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Return [(heading, body), ...] split on Markdown headings; falls back to one."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text.strip())]

    sections: list[tuple[str, str]] = []
    # Preamble before the first heading, if any.
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            sections.append(("", pre))

    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        sections.append((heading, body))
    return sections


def _split_long(body: str) -> list[str]:
    """Split an over-long body into <= MAX_CHARS pieces on paragraph/sentence breaks."""
    if len(body) <= MAX_CHARS:
        return [body] if body else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= TARGET_CHARS:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(para) <= MAX_CHARS:
            current = para
        else:
            # Sentence-level split for a giant paragraph.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            buf = ""
            for s in sentences:
                if len(buf) + len(s) + 1 <= TARGET_CHARS:
                    buf = f"{buf} {s}".strip()
                else:
                    if buf:
                        pieces.append(buf)
                    buf = s
            if buf:
                current = buf
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str) -> list[Chunk]:
    """Chunk ``text`` into a list of :class:`Chunk`."""
    text = (text or "").strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    idx = 0
    for heading, body in _split_into_sections(text):
        if not body:
            continue
        for piece in _split_long(body) or [body]:
            piece = piece.strip()
            if len(piece) < MIN_CHARS and chunks:
                # Merge tiny trailing fragments into the previous chunk.
                prev = chunks[-1]
                merged = f"{prev.text}\n\n{piece}".strip()
                chunks[-1] = Chunk(index=prev.index, heading=prev.heading, text=merged)
                continue
            chunks.append(Chunk(index=idx, heading=heading, text=piece))
            idx += 1
    return chunks
