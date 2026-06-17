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
    }
