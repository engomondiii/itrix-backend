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


def test_product_definitions_are_not_hardcoded_in_output_style_substitutions():
    """Technology/product facts come from the authorized current source layer.

    ``scrub`` remains an output-style/overclaim normalizer.  It must not revive the
    superseded Appendix-B ALPHA Core definition simply because a sentence mentions the
    product.  The governed system prompt and source-authority layer enforce the current
    product boundary.
    """
    out = scrub("ALPHA Core uses a lookup table execution model")
    assert "table-free index-ordered algebraic execution" not in out


def test_hard_block_only_quantified_benchmark_claims():
    assert has_hard_block("10x faster")
    assert has_hard_block("30% cheaper than the alternative")
    # Describing the proof method is safe. It must not send a normal product answer
    # into an indefinite human-review state merely because it names a baseline.
    assert not has_hard_block("benchmarked against an agreed baseline")
    assert not has_hard_block("benchmarked against the competition")
    assert not has_hard_block("a qualitative description of fit")


def test_scrub_softens_guarantees():
    assert "guarantee" not in scrub("we guarantee lower power").lower()
