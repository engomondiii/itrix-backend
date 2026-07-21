"""
Context assembly (Backend v6.0 §2.4, Architecture v2.6 §12.5).

Three rules: summarize never truncate; the visitor's current words are never compressed;
nothing is silently dropped.
"""

from __future__ import annotations

from apps.conversations.services.context_assembly import (
    PRIORITY_CURRENT_TURN,
    PRIORITY_KNOWLEDGE,
    PRIORITY_SYSTEM,
    assemble,
    build_context_note,
    summarize_closed_state,
)


def test_priority_one_to_three_are_never_trimmed():
    """
    An oversized turn can push out history, but can NEVER push out the governance
    contract, the approved knowledge, or the visitor's actual question.
    """
    result = assemble(
        system_contract="SYSTEM",
        journey_state="IN_REVIEW",
        disclosure_ceiling="public",
        current_turn="x" * 5000,
        knowledge_chunks=["k" * 5000],
        recent_turns=["r" * 5000],
        budget=1000,
    )
    kinds = {b.kind for b in result.blocks}
    assert "system" in kinds
    assert "knowledge" in kinds
    assert "current_turn" in kinds
    priorities = {b.priority for b in result.blocks}
    assert PRIORITY_SYSTEM in priorities
    assert PRIORITY_KNOWLEDGE in priorities
    assert PRIORITY_CURRENT_TURN in priorities


def test_dropping_history_is_recorded_not_silent():
    result = assemble(
        system_contract="S",
        journey_state="IN_REVIEW",
        disclosure_ceiling="public",
        current_turn="the question",
        recent_turns=["r" * 50_000],
        closed_state_summaries=["s" * 50_000],
        budget=2000,
    )
    assert result.dropped_kinds
    assert result.context_note
    assert result.complete is False


def test_a_conversation_within_budget_is_complete():
    result = assemble(
        system_contract="S",
        journey_state="IN_REVIEW",
        disclosure_ceiling="public",
        current_turn="short",
        recent_turns=["also short"],
        budget=100_000,
    )
    assert result.complete is True
    assert result.context_note == ""


def test_the_context_note_is_plain_and_reassuring():
    note = build_context_note(["recent_turns", "attachments"])
    assert "could not be included" in note
    # It must tell them what to DO, not just that something is missing.
    assert "brought back into view" in note
    for hedge in ("unfortunately", "sorry", "error"):
        assert hedge not in note.lower()


def test_no_note_when_nothing_was_dropped():
    assert build_context_note([]) == ""


def test_the_journey_state_and_ceiling_are_always_in_the_header():
    """The model must never be asked to answer without knowing what it may disclose."""
    result = assemble(
        system_contract="SYSTEM",
        journey_state="ASSESSMENT",
        disclosure_ceiling="nda_only",
        current_turn="q",
    )
    text = result.text()
    assert "journey_state=ASSESSMENT" in text
    assert "disclosure_ceiling=nda_only" in text


def test_summaries_are_deterministic():
    """
    A summary replayed into every later turn must be auditable and reproducible. A
    generated one would put un-governed text into the model's context repeatedly.
    """

    class FakeMessage:
        def __init__(self, kind, body):
            self.sender_kind = kind
            self.body = body

    messages = [FakeMessage("visitor", "our solver drifts"), FakeMessage("agent", "understood")]
    first = summarize_closed_state(messages)
    second = summarize_closed_state(messages)
    assert first == second
    assert "Visitor:" in first
