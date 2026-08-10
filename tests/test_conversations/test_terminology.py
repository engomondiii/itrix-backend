"""
The internal stack name never reaches a visitor (change request, 2026-08-10).

The reported transcript said "At the heart of itriX is what's called the
Knowledge Core". Two layers make sure that cannot recur: the system prompt now
teaches the public name (itriX Technologies) and forbids the internal one, and
the settle path in both transports normalises whatever the model produced.
These tests pin both layers.
"""

from __future__ import annotations

from apps.ai_engine.services.system_prompt_builder import build_conversation_system_prompt
from apps.conversations.services.terminology import normalise_outbound


# ── The deterministic layer ──────────────────────────────────────────────────
def test_the_internal_name_is_replaced():
    out = normalise_outbound("At the heart of itriX is the Knowledge Core, a triad.")
    assert "Knowledge Core" not in out
    assert "itriX Technologies, a triad." in out


def test_the_leading_article_is_swallowed():
    # "the itriX Technologies is" would be broken English; the article goes with
    # the name it modified.
    assert normalise_outbound("The Knowledge Core is a triad.") == "itriX Technologies is a triad."


def test_casing_variants_are_caught():
    for s in ("knowledge core", "KNOWLEDGE CORE", "Knowledge core", "the KNOWLEDGE Core"):
        assert "itriX Technologies" == normalise_outbound(s)


def test_wrapped_whitespace_is_caught():
    # A streamed reply can wrap the phrase across a line break.
    assert normalise_outbound("the Knowledge\n Core triad") == "itriX Technologies triad"


def test_unrelated_text_is_untouched():
    for s in (
        "core knowledge of the domain",
        "the knowledge that core computation carries cost",
        "a knowledge-driven core team",
        "",
    ):
        assert normalise_outbound(s) == s


def test_composites_do_not_half_match():
    assert normalise_outbound("knowledge cores are plural") == "knowledge cores are plural"


# ── The prompt layer ─────────────────────────────────────────────────────────
def test_the_conversation_prompt_never_teaches_the_internal_name():
    prompt = build_conversation_system_prompt(
        product_route="alpha_compute",
        license_pathway=None,
        tier=1,
        pressures=[],
        chunks=[],
    )
    # The internal name appears once — inside the rule that forbids using it.
    # The affirmative brand teaching uses the public name.
    assert "itriX Technologies" in prompt
    assert "INTERNAL" in prompt
    assert "must never appear" in prompt
