"""Prohibited-language + Appendix-B canonical wording + hard-block."""

from __future__ import annotations

import pytest

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


def test_scrub_softens_affirmative_guarantee_grammatically():
    out = scrub("we guarantee lower power")
    assert out == "we do not guarantee lower power"
    assert "aims to" not in out


@pytest.mark.parametrize(
    "text",
    [
        "Rather than a blanket guarantee, we evaluate the workload.",
        "Those results do not transfer as guarantees to other workloads.",
        "Guaranteed performance improvements are not something we can provide.",
        "Guaranteed performance improvements are not a claim itriX makes.",
        "Guaranteed results aren't claims we make.",
        "Guaranteed savings are not something itriX promises.",
        "We don't make guaranteed performance claims.",
        "We cannot guarantee performance improvements.",
        "Performance improvements are not guaranteed.",
        "Rather than making a blanket guarantee, itriX evaluates the workload.",
        "Those results should not be treated as guarantees for other workloads.",
        "I can't provide guaranteed performance figures.",
    ],
)
def test_safe_guarantee_refusal_and_discussion_remain_natural(text):
    assert contains_prohibited(text) is False
    assert scrub(text) == text
    assert "aims to" not in scrub(text)
    assert "targeted performance" not in scrub(text)


@pytest.mark.parametrize(
    "text",
    [
        "We guarantee lower costs.",
        "itriX guarantees better performance.",
        "ALPHA guarantees faster execution.",
        "ASTOP guarantees perfect results.",
        "We guarantee this will work for every workload.",
        "Guaranteed performance improvements are available.",
        "Guaranteed savings are part of ALPHA Compute.",
        "ALPHA Compute provides guaranteed performance.",
        "We offer guaranteed results.",
    ],
)
def test_affirmative_guarantees_remain_governed(text):
    assert contains_prohibited(text) is True
    out = scrub(text)
    assert out != text
    assert "aims to" not in out


def test_live_guarantee_refusal_context_preserves_meaning():
    text = "Guaranteed performance improvements aren't a claim itriX makes."
    out = scrub(text)
    assert contains_prohibited(text) is False
    assert out == text
    assert "potential performance improvements aren't a claim" not in out.lower()


def test_live_guarantee_discussion_regression_does_not_mangle_grammar():
    text = (
        "Quantitative results do not transfer as guarantees to other workloads. "
        "So rather than a blanket guarantee, we evaluate the workload."
    )
    out = scrub(text)
    assert out == text
    assert "aims to to" not in out
    assert "blanket aims to" not in out
