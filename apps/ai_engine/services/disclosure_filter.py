"""
Disclosure filter.

Enforces the five-tier disclosure model on retrieved knowledge before it can influence a
public-facing result. The public result page may only be built from ``public`` (and, when
an NDA context applies, ``nda_only``) material; ``controlled_public`` is allowed only in
controlled contexts; ``internal_only`` and ``prohibited`` are never exposed.

This runs on retrieved chunks (by their ``disclosure_level`` metadata) and on the proof
list, so nothing above the caller's allowed tier reaches the visitor.
"""

from __future__ import annotations

# Ordering from most to least open.
DISCLOSURE_ORDER = ["public", "controlled_public", "nda_only", "internal_only", "prohibited"]

# What each context is permitted to see.
CONTEXT_ALLOWED = {
    "public": {"public"},
    "controlled": {"public", "controlled_public"},
    "nda": {"public", "controlled_public", "nda_only"},
    "internal": {"public", "controlled_public", "nda_only", "internal_only"},
}

# Never exposed outside internal tooling, regardless of context.
NEVER_PUBLIC = {"internal_only", "prohibited"}


def allowed_levels(context: str) -> set[str]:
    return CONTEXT_ALLOWED.get(context, {"public"})


def is_allowed(level: str, *, context: str = "public") -> bool:
    level = (level or "public").lower()
    if level == "prohibited":
        return False
    return level in allowed_levels(context)


def filter_chunks(chunks: list[dict], *, context: str = "public") -> list[dict]:
    """
    Keep only chunks whose ``disclosure_level`` is allowed in ``context``.

    ``chunks`` items are dicts carrying at least ``disclosure_level`` (directly or under
    ``metadata``).
    """
    permitted = allowed_levels(context)
    kept: list[dict] = []
    for chunk in chunks:
        level = (chunk.get("disclosure_level") or chunk.get("metadata", {}).get("disclosure_level") or "public").lower()
        if level in NEVER_PUBLIC and context != "internal":
            continue
        if level in permitted:
            kept.append(chunk)
    return kept


def filter_proofs(proofs: list[dict], *, context: str = "public") -> list[dict]:
    """Filter proof-preview items by their ``disclosure`` field for the given context."""
    permitted = allowed_levels(context)
    out: list[dict] = []
    for proof in proofs:
        level = (proof.get("disclosure") or "public").lower()
        if level in NEVER_PUBLIC and context != "internal":
            continue
        if level in permitted:
            out.append(proof)
    return out
