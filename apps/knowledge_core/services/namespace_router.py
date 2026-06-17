"""
Namespace router.

Normalises and validates the Pinecone namespace for a document. Namespaces group
knowledge by product/topic (e.g. ``alpha-compute``, ``alpha-core``, ``proofs``). The
router slugifies free-text namespaces and offers a small set of canonical names so
ingestion and retrieval agree on spelling.
"""

from __future__ import annotations

from slugify import slugify

CANONICAL_NAMESPACES = {
    "alpha-compute",
    "alpha-core",
    "proofs",
    "technology",
    "licensing",
    "company",
    "general",
}


def normalize_namespace(namespace: str | None) -> str:
    """Return a slugified namespace, defaulting to 'general'."""
    slug = slugify(namespace or "") or "general"
    return slug


def is_canonical(namespace: str) -> bool:
    return normalize_namespace(namespace) in CANONICAL_NAMESPACES
