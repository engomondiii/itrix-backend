"""Verified public evidence preview for My Review.

Only references that are explicitly known and validated may render.  The previous
placeholder ``arXiv:2401.00000`` was a template value and is intentionally removed.
An absent proof is safer than a fabricated one.
"""
from __future__ import annotations

_PUBLIC_PROOFS = [
    {
        "title": "FQNM research",
        "status": "arXiv preprint",
        "disclosure": "public",
        "reference": "arXiv:2604.06947 [math.NA]",
    },
]


def build_proof_preview(*, product_route: str, tier: int, context: str = "public") -> list[dict]:
    """Return verified, public-safe evidence only.

    We deliberately do not render NDA-only placeholders or generic customer-result
    claims.  Controlled evidence belongs in an authorized workspace after the
    corresponding disclosure gate, not on a shareable My Review page.
    """
    return [dict(item) for item in _PUBLIC_PROOFS]
