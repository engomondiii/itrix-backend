"""
SECURITY INVARIANT 3 — the folder IS the access-control decision
(Backend v6.0 §8.1, §19.6).

THE CI TRIPWIRE. Placing a file in ``knowledge_docs/public/`` publishes it to every
anonymous visitor through the agents — and in v6.0 those agents STREAM to unidentified
visitors by default, so the blast radius of a mis-filed document is LARGER than it was.

This test fails the build when a never-public pattern lands in a visitor-reachable tier.
It is intentionally a filename check rather than a content check: content analysis is
fallible and slow, whereas a filename containing "pricing" or "thesis" in public/ is
unambiguous and catches the realistic mistake — someone dropping a file in the wrong
folder.
"""

from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
KNOWLEDGE_DOCS = REPO_ROOT / "knowledge_docs"

VISITOR_REACHABLE_TIERS = ("public", "controlled_public")

# Patterns that must NEVER appear in a tier an unidentified visitor can reach.
NEVER_PUBLIC_PATTERNS = (
    "pricing",
    "investor",
    "data_room",
    "dataroom",
    "thesis",
    "kickoff",
    "playbook",
    "internal",
    "roadmap",
    "term_sheet",
    "valuation",
    "cap_table",
)


def _files_in(tier: str):
    tier_dir = KNOWLEDGE_DOCS / tier
    if not tier_dir.exists():
        return []
    return [p for p in sorted(tier_dir.iterdir()) if p.is_file() and p.name != ".gitkeep"]


@pytest.mark.parametrize("tier", VISITOR_REACHABLE_TIERS)
def test_no_never_public_pattern_in_visitor_reachable_tier(tier):
    offenders = []
    for path in _files_in(tier):
        lowered = path.name.lower().replace(" ", "_")
        for pattern in NEVER_PUBLIC_PATTERNS:
            if pattern in lowered:
                offenders.append(f"{tier}/{path.name} matches {pattern!r}")
                break
    assert not offenders, (
        "never-public material is reachable by unidentified visitors:\n  "
        + "\n  ".join(offenders)
    )


def test_public_tier_holds_only_approved_knowledge_core_material():
    """
    The public tier is an ALLOW-LIST, not a dumping ground.

    A document belongs here only if it was WRITTEN TO BE PUBLISHED — not merely "contains
    nothing catastrophic".
    """
    approved = {
        "4_1_AXIOM_Overview_v2.0.docx",
        "4_2_CRE_Overview_v2.0.docx",
        "4_3_FQNM_Overview_v2.0.docx",
        "4_4_Unified Mathematical View_Inventor_V2.0.docx",
        "5_1_ALPHA_Compute_Overview_v2.0.docx",
        "5_2_ALPHA Core Product Overview_V2.0.docx",
        "6_Computational Workload and Platform Materials_V2.0.docx",
        "7_AI-Aggravated Bottleneck Materials_V2.0.docx",
        "Brand Story of itriX.docx",
        "alpha_compute_problemology_public.md",
        "alpha_core_problemology_public.md",
        "brand_story_company_public.md",
    }
    actual = {p.name for p in _files_in("public")}
    unexpected = actual - approved
    assert not unexpected, (
        "unapproved documents in the public tier:\n  " + "\n  ".join(sorted(unexpected))
    )


def test_the_masters_thesis_is_not_publicly_reachable():
    """Named explicitly: it is the single highest-value trade-secret document."""
    for tier in VISITOR_REACHABLE_TIERS:
        for path in _files_in(tier):
            assert "thesis" not in path.name.lower(), f"{path.name} is reachable at {tier}"


def test_the_pricing_policy_is_not_publicly_reachable():
    """Pricing is never public and is never emitted by an agent (§19.5, R6)."""
    for tier in VISITOR_REACHABLE_TIERS:
        for path in _files_in(tier):
            assert "pricing" not in path.name.lower(), f"{path.name} is reachable at {tier}"
