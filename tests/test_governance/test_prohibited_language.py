"""Prohibited-language + Appendix-B canonical wording + hard-block."""

from __future__ import annotations

from apps.ai_engine.services.prohibited_language_checker import (
    contains_prohibited,
    find_violations,
    has_hard_block,
    scrub,
)


def test_prohibited_claims_detected():
    assert contains_prohibited("this guarantees perfect accuracy")
    assert "always" in " ".join(find_violations("it always works"))


def test_alpha_core_canonical_substitution():
    out = scrub("ALPHA Core uses a lookup table execution model")
    assert "table-free index-ordered algebraic execution" in out
    assert "lookup table execution" not in out.lower()


def test_hard_block_benchmarks_and_competitor_numbers():
    assert has_hard_block("10x faster")
    assert has_hard_block("30% cheaper than the alternative")
    assert has_hard_block("benchmarked against the competition")
    assert not has_hard_block("a qualitative description of fit")


def test_scrub_softens_guarantees():
    assert "guarantee" not in scrub("we guarantee lower power").lower()
