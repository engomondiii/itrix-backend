"""
Metadata tagger.

Builds the metadata dict attached to each vector in Pinecone. Keeping disclosure level,
namespace, document id, heading, and a text preview on every vector lets the AI engine's
disclosure filter exclude non-public chunks *at query time* without a second lookup.
"""

from __future__ import annotations


def build_chunk_metadata(*, document, chunk) -> dict:
    """Return the Pinecone metadata for a single chunk."""
    return {
        "document_id": str(document.id),
        "document_title": document.title,
        "namespace": chunk.namespace or document.namespace,
        "disclosure_level": chunk.disclosure_level or document.disclosure_level,
        "chunk_index": chunk.chunk_index,
        "heading": (chunk.heading or "")[:512],
        # A short preview is handy for debugging retrieval; full text lives in the DB.
        "preview": (chunk.text or "")[:280],
        # ── v4.0 Problemology metadata (additive) ────────────────────────────
        # These tie each chunk to a commercial function + audience + claim level so
        # agents can retrieve by function and governance can bound claims. Chunks
        # ingested before this migration simply default here and still retrieve.
        "problemology_core": _problemology_core(document, chunk),
        "audience": _audience(document, chunk),
        "claim_level": _claim_level(document, chunk),
    }


# ── v4.0 metadata derivation (additive, safe defaults) ───────────────────────
# The nine Problemology cores (Backend v4 §5.1).
_CORES = (
    "problem", "secret", "solution", "product", "purpose",
    "proof", "buyer", "objection", "commercialization",
)


def _problemology_core(document, chunk) -> str:
    """Explicit chunk/doc value wins; otherwise infer from heading keywords, else general."""
    explicit = getattr(chunk, "problemology_core", "") or getattr(document, "problemology_core", "")
    if explicit in _CORES:
        return explicit
    text = f"{getattr(chunk, 'heading', '') or ''} {getattr(chunk, 'text', '') or ''}".lower()
    for core in _CORES:
        if core in text:
            return core
    return "general"


def _audience(document, chunk) -> str:
    """One of technical|strategic|investor|media|general (default general)."""
    explicit = getattr(chunk, "audience", "") or getattr(document, "audience", "")
    valid = {"technical", "strategic", "investor", "media", "general"}
    return explicit if explicit in valid else "general"


def _claim_level(document, chunk) -> int:
    """
    The claim level a chunk is approved to support. Explicit value wins; otherwise map
    the disclosure level to a conservative claim level (public → 1, controlled → 2,
    nda_only → 3, internal → 4). Governance uses this as a retrieval-time hint.
    """
    explicit = getattr(chunk, "claim_level", None)
    if isinstance(explicit, int) and explicit:
        return explicit
    disclosure = (getattr(chunk, "disclosure_level", "") or getattr(document, "disclosure_level", "") or "").lower()
    return {
        "public": 1,
        "controlled_public": 2,
        "nda_only": 3,
        "internal_only": 4,
    }.get(disclosure, 1)
