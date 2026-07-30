"""
THE MARKER-NORMALISED SECOND PASS (Architecture v2.8 §19.9 rule 5, Backend v7.1 Phase 2).

── WHAT THESE TESTS ARE PROTECTING ─────────────────────────────────────────

Every case in ``EVASIONS`` below is a string that RENDERS as a prohibited claim and PASSES
a raw-text match. Before this pass existed, each one reached the visitor while the guard
reported clean — the worst possible failure shape, because the metric that would have
warned us said everything was fine.

This is also the precondition for ``NEXT_PUBLIC_ENABLE_MARKDOWN_TURNS``. If these tests
fail, that flag must not be on.
"""

from __future__ import annotations

import pytest

from apps.governance.services import stream_guard
from apps.governance.services.marker_normalise import differs, normalise_markers

pytestmark = pytest.mark.django_db


# ── THE EVASION CASES ────────────────────────────────────────────────────────
#
# Every entry is (markup, rendered) where RENDERED matches a pattern that is actually in
# the shared prohibited set — verified against
# ``apps.ai_engine.services.prohibited_language_checker``, not invented:
#
#     HARD_BLOCK      \d+\s?x faster · \d+%\s+faster · benchmarked against
#     PROHIBITED_CLAIM  "always faster" · "guarantees lower power"
#     CANONICAL         \bmagic\b · lookup-table execution
#     STREAM_ONLY       $-prefixed figures · N% of the value
#
# An earlier draft of this file used "guarantee", which is NOT in the set — so the tests
# failed and correctly said the guard was not halting. Writing tests against a pattern set
# you assumed rather than read is how a security test comes to assert nothing.
EVASIONS = [
    # Emphasis splitting a hard-block pattern.
    ("10x fa*st*er", "10x faster"),
    ("**10x faster**", "10x faster"),
    # A link label.
    ("[10x faster](#anchor)", "10x faster"),
    # A code span. The raw buffer has backticks between the tokens.
    ("`30% faster`", "30% faster"),
    # Nested block markers — a heading inside a blockquote.
    ("> ## 10x faster", "10x faster"),
    # A list item wrapping a prohibited claim.
    ("- **always faster**", "always faster"),
    ("1. 10x fa*ster*", "10x faster"),
    # A zero-width space inside the phrase. Not Markdown, same class of evasion.
    ("10x fa\u200bster", "10x faster"),
    # A canonical-wording violation wrapped in emphasis.
    ("this is *magic*", "this is magic"),
    # A pricing figure the raw matcher misses because `*` sits between `$` and the digits.
    ("$*3M*", "$3M"),
    # THE CASE THE WHITESPACE-COLLAPSE FIX EXISTS FOR: a prohibited figure laid out as a
    # table row. Stripping pipes left double spaces, and the pattern allows only one.
    ("| 40 | % | of the value |", " 40 % of the value "),
]


# Markup that renders WITH its delimiters intact, and therefore does NOT match. These are
# the false-positive cases: a guard that halted on them would be discarding harmless answers.
NOT_EVASIONS = [
    (r"guarantees lower po\*wer", "guarantees lower po*wer"),
    (r"10x fa\*st\*er", "10x fa*st*er"),
    # NOTE `\*magic\*` is deliberately NOT here. ``\bmagic\b`` is a whole-word pattern and
    # a word boundary sits between `*` and `m`, so the RAW pass matches it — correctly, because
    # the rendered text `this is *magic*` really does contain the word. Escaping a delimiter
    # only defeats a pattern whose own characters the delimiter interrupts.
]


@pytest.mark.parametrize("markup,rendered", EVASIONS)
def test_normalisation_recovers_the_rendered_text(markup, rendered):
    assert normalise_markers(markup) == rendered


@pytest.mark.parametrize("markup,rendered", NOT_EVASIONS)
def test_an_escaped_delimiter_renders_literally_and_is_not_an_evasion(markup, rendered):
    r"""
    ── THE FALSE-POSITIVE SIDE, AND IT MATTERS AS MUCH AS THE OTHER ONE ────

    ``10x fa\*st\*er`` displays as ``10x fa*st*er`` — asterisks and all — which does not
    match ``\d+\s?x faster``. It is not an evasion, and halting on it would discard a
    harmless answer and route it to human review for nothing.

    An earlier version of the normaliser stripped the backslash and let the delimiter sweep
    remove the asterisk too, producing ``10x faster`` and exactly that false halt. A guard
    that cries wolf is a guard someone disables, so the escaped character is now encoded onto
    a sentinel and restored.
    """
    assert normalise_markers(markup) == rendered


@pytest.mark.parametrize("markup,_rendered", NOT_EVASIONS)
def test_the_guard_stays_quiet_on_an_escaped_delimiter(markup, _rendered):
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in markup:
        assert stream_guard.inspect(state, char) is None, (
            f"false halt on {markup!r}, which renders with its delimiters intact"
        )
    assert state.halted is False


def test_plain_prose_is_unchanged_and_skips_the_second_pass():
    """
    The skip matters for latency: the second pass runs per token, and plain prose is the
    overwhelming majority of tokens. It must cost one string comparison, not a pattern sweep.
    """
    text = "Your inference cost is rising faster than the value it creates."
    assert normalise_markers(text) == text
    assert differs(text) is False


def test_newlines_survive_normalisation():
    """
    Collapsing them would join unrelated lines into strings that never render — which would
    produce FALSE halts, and a guard that cries wolf is a guard someone disables.
    """
    assert normalise_markers("line one\nline two") == "line one\nline two"


def test_a_table_row_normalises_so_the_pricing_rule_can_match():
    """
    ── A REAL BUG THIS TEST WAS WRITTEN AFTER FINDING ──────────────────────
    Stripping table pipes left DOUBLE spaces: "| 40 | % |" became " 40  % ". The pricing
    rule is ``\\d{1,3}\\s?%`` — one optional space — so two spaces defeated it, and a
    prohibited figure laid out as a table row passed both passes.

    Horizontal whitespace runs are now collapsed. Newlines are not.
    """
    normalised = normalise_markers("| 40 | % |")
    assert "  " not in normalised
    assert "40 %" in normalised


@pytest.mark.parametrize("markup,_rendered", EVASIONS)
def test_the_guard_halts_on_every_evasion(markup, _rendered):
    """
    The end-to-end property. Fed token by token, exactly as the consumer feeds it.

    ``scan`` is used for the whole-text case below; this one goes through ``inspect`` so the
    sliding window and the second pass are both exercised the way they run in production.
    """
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()

    hit = None
    for char in markup:
        hit = stream_guard.inspect(state, char)
        if hit is not None:
            break

    assert hit is not None, f"the guard did not halt on {markup!r}"
    assert state.halted is True


def test_a_normalised_hit_records_WHICH_pass_caught_it():
    """
    The two mean different things: a RAW hit is a model saying a prohibited thing plainly; a
    NORMALISED hit is a model saying it inside markup, which is the one to investigate first.

    Without the field the two are indistinguishable in the cockpit.
    """
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in "10x fa*st*er":
        if stream_guard.inspect(state, char) is not None:
            break

    assert state.first_hit is not None
    assert state.first_hit.matcher_pass == stream_guard.PASS_NORMALISED


def test_a_plain_prohibited_claim_still_records_as_raw():
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in "it is 10x faster":
        if stream_guard.inspect(state, char) is not None:
            break

    assert state.first_hit is not None
    assert state.first_hit.matcher_pass == stream_guard.PASS_RAW


def test_scan_runs_both_passes_for_the_settle_stage():
    """
    Settle is where a halt becomes an ``under_review`` replacement rather than a discard —
    and it is the path used whenever the socket handshake fails. Missing the normalised pass
    here would let a markup-wrapped claim through on HTTP, which is the fallback path that
    exists precisely so a failed socket does not lose the visitor's answer.
    """
    stream_guard.reset_pattern_cache()
    hits = stream_guard.scan("It is 10x fa**st**er in our tests.")
    assert hits, "scan found nothing in a markup-SPLIT prohibited claim"
    # `**10x faster**` would be caught by the RAW pass — the delimiters sit outside the
    # match — so it proves nothing about the second pass. The pattern has to be SPLIT.
    assert any(h.matcher_pass == stream_guard.PASS_NORMALISED for h in hits)


def test_scan_does_not_double_report_the_same_match():
    """
    A claim that matches BOTH passes must be reported once.

    Reporting it twice would double the halt count, and §6.4 reads a rising halt rate as
    retrieval or prompt drift. A metric that inflates itself for a formatting reason would
    manufacture a drift signal out of nothing.
    """
    stream_guard.reset_pattern_cache()
    hits = stream_guard.scan("it is 10x faster")
    keys = [(h.pattern, h.matched_text) for h in hits]
    assert len(keys) == len(set(keys)), f"duplicate hits reported: {keys}"


def test_a_normalised_hit_reports_a_position_it_can_defend():
    """
    Normalisation is not length-preserving, so an offset into the normalised text would be a
    confident lie about where the claim sits in the real buffer. The window start is what the
    guard actually knows.
    """
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in "10x fa*st*er":
        if stream_guard.inspect(state, char) is not None:
            break
    assert state.first_hit.position >= 0


def test_the_halt_payload_still_carries_no_partial_text():
    """
    Unchanged by Phase 2, and worth re-pinning: the visitor sees the approved halted wording
    and nothing about what matched. The matched pattern goes to the cockpit, never to the
    client (§10.5).
    """
    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in "10x fa*st*er":
        if stream_guard.inspect(state, char) is not None:
            break

    payload = stream_guard.halt_payload(state, thread_id="t", message_id="m")
    assert "10x" not in payload["replacement_body"]
    assert "matched_text" not in payload
    assert "pattern" not in payload


def test_the_recorded_hit_persists_the_matcher_pass():
    from apps.governance.models import StreamGuardHit

    stream_guard.reset_pattern_cache()
    state = stream_guard.new_state()
    for char in "10x fa*st*er":
        if stream_guard.inspect(state, char) is not None:
            break

    stream_guard.record_hits(state, message_id="m1", thread_id="t1", agent_key="concierge", plane="anonymous")
    row = StreamGuardHit.objects.order_by("-created_at").first()
    assert row is not None
    assert row.matcher_pass == "normalised"
