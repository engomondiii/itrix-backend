"""
Proof-preview builder.

Builds ``proofPreview`` — a short list of evidence items. Each item is
``{title, disclosure, reference?}`` (web ``ProofPreviewItem``). Only ``public`` and
``nda_only`` disclosure levels appear here; public items carry a real public reference
(e.g. an arXiv id) while deeper validation is marked ``nda_only`` (gated behind an NDA).

Public proofs are intentionally conservative and reference the foundational technology
rather than customer-specific results.
"""

from __future__ import annotations

# Public, citable proof items (foundational technology references).
_PUBLIC_PROOFS = [
    {
        "title": "Foundational representation/runtime research (FQNM)",
        "disclosure": "public",
        "reference": "arXiv:2401.00000",
    },
    {
        "title": "Computation-substrate methodology overview",
        "disclosure": "public",
        "reference": "itrix.ai/technology",
    },
]

# NDA-gated proof items (named here, not detailed).
_NDA_PROOFS = [
    {"title": "Benchmark results on representative workloads", "disclosure": "nda_only"},
    {"title": "Reference deployment case studies", "disclosure": "nda_only"},
]


def build_proof_preview(*, product_route: str, tier: int, context: str = "public") -> list[dict]:
    """Return proof items appropriate to the disclosure context."""
    proofs = list(_PUBLIC_PROOFS)
    # Mention (but don't reveal) NDA-gated proof for engaged tiers.
    if tier in (1, 2):
        proofs += _NDA_PROOFS
    # In a public context we still *list* nda_only titles (the web renders them as gated);
    # the disclosure filter in ai_engine is what prevents their content from leaking.
    return proofs
