"""
Streaming governance Part 1 — the pre-flight envelope (Backend v6.0 §6.1).

The rule: a turn that would require LEVEL-4 OR LEVEL-5 approval DOES NOT STREAM AT ALL.
Nothing about a high-risk claim is ever rendered provisionally, because a claim that
streams for two seconds and is then retracted has already been read.
"""

from __future__ import annotations

import pytest

from apps.governance.services import stream_envelope


def test_low_claim_on_public_plane_may_stream():
    envelope = stream_envelope.build(plane="public", journey_state=2, intended_claim_level=1)
    assert envelope.may_stream is True


@pytest.mark.parametrize("level", [4, 5])
def test_high_claim_never_streams(level):
    envelope = stream_envelope.build(plane="team", journey_state=9, intended_claim_level=level)
    assert envelope.may_stream is False
    assert envelope.requires_approval is True
    assert envelope.replacement_body == stream_envelope.UNDER_REVIEW_WORDING


def test_retrieved_chunk_level_raises_the_effective_level():
    """
    Answering FROM a level-4 chunk is a level-4 claim, regardless of how the agent
    framed its intent. The agent does not get to grade its own output.
    """
    envelope = stream_envelope.build(
        plane="public", journey_state=2, intended_claim_level=1, retrieved_chunk_levels=[4]
    )
    assert envelope.may_stream is False


def test_arrival_state_caps_at_ask_never_assert():
    """State 1 may ask, never assert — so anything above level 1 must not stream there."""
    envelope = stream_envelope.build(plane="public", journey_state=1, intended_claim_level=2)
    assert envelope.may_stream is False


def test_the_under_review_wording_is_calm_and_explains_nothing():
    """
    §13.3: the visitor sees ONLY this. It must not apologise excessively and must never
    explain what was blocked or why.
    """
    wording = stream_envelope.UNDER_REVIEW_WORDING
    assert "specialist is reviewing" in wording
    for leak in ("blocked", "prohibited", "violation", "sorry", "error"):
        assert leak not in wording.lower()


def test_the_halted_wording_does_not_explain_either():
    wording = stream_envelope.HALTED_WORDING
    assert "stopped that response" in wording
    for leak in ("blocked", "prohibited", "violation"):
        assert leak not in wording.lower()
