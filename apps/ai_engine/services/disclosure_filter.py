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
DISCLOSURE_ORDER = [
    "public", "controlled_public", "nda_only", "customer_contract",
    "internal_only", "prohibited",
]

# What each context is permitted to see.
CONTEXT_ALLOWED = {
    "public": {"public"},
    "controlled": {"public", "controlled_public"},
    "nda": {"public", "controlled_public", "nda_only"},
    # ── v6.0: the SIXTH TIER ─────────────────────────────────────────────────
    # customer_contract material is SCOPED PER CUSTOMER and NEVER CROSS-SERVED.
    # Reaching this tier is not enough on its own — ``customer_scope`` must also
    # match, and ``filter_chunks`` enforces that separately below. A customer who
    # can see the tier must still not see another customer's contract material.
    "customer_contract": {"public", "controlled_public", "nda_only", "customer_contract"},
    "internal": {
        "public", "controlled_public", "nda_only", "customer_contract", "internal_only",
    },
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


def filter_chunks(
    chunks: list[dict], *, context: str = "public", customer_scope: str = ""
) -> list[dict]:
    """
    Keep only chunks whose ``disclosure_level`` is allowed in ``context``.

    ``customer_scope`` adds the SECOND gate for the sixth tier. A customer_contract chunk
    is served only when its own scope matches the caller's — an empty caller scope can
    never match a scoped chunk, so the default is closed.
    """
    permitted = allowed_levels(context)
    kept: list[dict] = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {}) or {}
        level = (
            chunk.get("disclosure_level") or metadata.get("disclosure_level") or "public"
        ).lower()
        if level in NEVER_PUBLIC and context != "internal":
            continue
        if level not in permitted:
            continue

        # THE SECOND GATE. customer_contract material is scoped per customer and NEVER
        # cross-served. The team plane is exempt because internal review must be able to
        # see the material it is reviewing.
        if level == "customer_contract" and context != "internal":
            chunk_scope = str(chunk.get("customer_scope") or metadata.get("customer_scope") or "")
            if not chunk_scope or chunk_scope != str(customer_scope or ""):
                continue

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
