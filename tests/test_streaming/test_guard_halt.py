"""
Streaming governance Part 2 — the stream guard (Backend v6.0 §6.2).

A HARD STOP, not a warning. The critical property is CROSS-TOKEN matching: tokens arrive
in fragments, so "3" + "0" + "% " + "faster" is four tokens and one violation. A
per-token matcher would never see it.
"""

from __future__ import annotations

import pytest

from apps.governance.services import stream_guard


def _feed(tokens):
    state = stream_guard.new_state()
    for token in tokens:
        hit = stream_guard.inspect(state, token)
        if hit is not None:
            return state, hit
    return state, None


def test_clean_text_streams_without_a_hit():
    state, hit = _feed(["We ", "would ", "examine ", "the ", "workload ", "structure."])
    assert hit is None
    assert state.halted is False


def test_benchmark_figure_split_across_tokens_is_caught():
    """THE CASE THAT MATTERS. Four tokens, one violation."""
    state, hit = _feed(["Alpha is ", "3", "0", "% ", "faster", " than before"])
    assert hit is not None
    assert state.halted is True
    assert hit.category == "benchmark"


def test_lookup_table_phrasing_is_caught():
    """
    ALPHA Core is ALWAYS 'table-free index-ordered algebraic execution' and must NEVER
    be described as lookup-table execution (§19.5).
    """
    _state, hit = _feed(["It uses ", "lookup-table ", "execution ", "internally"])
    assert hit is not None
    assert hit.category == "canonical_wording"


def test_pricing_is_caught():
    _state, hit = _feed(["The assessment costs ", "$", "50,000", " upfront"])
    assert hit is not None
    assert hit.category == "pricing"


def test_exclusivity_terms_are_caught():
    _state, hit = _feed(["We can offer an ", "exclusive license", " for your field"])
    assert hit is not None
    assert hit.category == "exclusivity"


def test_inferred_identity_assertion_is_caught():
    """
    PERSONALIZATION WITHOUT PROFILING (§4). The pitch may be tailored; it may never say
    so out loud.
    """
    _state, hit = _feed(["Based on your ", "company", ", we think..."])
    assert hit is not None
    assert hit.category == "inferred_identity"


def test_guarantee_language_is_caught():
    _state, hit = _feed(["We ", "guarantee ", "lower energy costs"])
    assert hit is not None


def test_halt_stops_processing_immediately():
    state = stream_guard.new_state()
    stream_guard.inspect(state, "30% faster")
    before = state.accumulated
    stream_guard.inspect(state, " and more text")
    assert state.accumulated == before, "no token may be accepted after a halt"


def test_halt_payload_carries_no_partial_text():
    """
    A halted message's partial text is DISCARDED. Including it in the payload would
    defeat the entire mechanism.
    """
    state, _hit = _feed(["Alpha is 30% faster than the alternative"])
    payload = stream_guard.halt_payload(state, thread_id="t1", message_id="m1")
    assert "30%" not in str(payload)
    assert payload["reason"] == "governance_halt"
    assert "specialist" in payload["replacement_body"]


def test_scan_finds_every_hit_not_just_the_first():
    """At settle time the cockpit wants the whole picture, not the first match."""
    hits = stream_guard.scan("It is 30% faster and we guarantee $100,000 of savings")
    assert len(hits) >= 2


def test_disabling_the_guard_is_explicit(settings):
    settings.STREAM_GUARD_ENABLED = False
    state = stream_guard.new_state()
    assert stream_guard.inspect(state, "30% faster") is None
    settings.STREAM_GUARD_ENABLED = True


def test_pattern_set_is_single_sourced_with_the_settle_checker():
    """
    §11.1: the prohibited-pattern set has EXACTLY ONE definition, so a pattern cannot be
    enforced at settle but missed mid-stream.
    """
    from apps.ai_engine.services import prohibited_language_checker as plc
    from apps.governance.services.claim_checker import shared_pattern_set

    shared = shared_pattern_set()
    assert shared["hard_block"] == list(plc.HARD_BLOCK_PATTERNS)
    assert shared["prohibited_claims"] == list(plc.PROHIBITED_CLAIMS)

    # Every hard-block pattern must actually be live in the guard.
    guard_patterns = {name for name, _c, _cat in stream_guard._patterns()}
    for pattern in plc.HARD_BLOCK_PATTERNS:
        assert pattern in guard_patterns
