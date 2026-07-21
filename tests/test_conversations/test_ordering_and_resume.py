"""
Message ordering and resumption (Backend v6.0 §7.2, Architecture v2.6 §14.4).

Three guarantees, each closing a specific failure: monotonic seq, gap detection, resume.
"""

from __future__ import annotations

import pytest

from apps.conversations.services import ingest, threads as thread_svc
from apps.realtime.services.sequence import (
    detect_gap,
    latest_seq,
    messages_since,
    next_seq,
    resume_payload,
)

pytestmark = pytest.mark.django_db


def _thread():
    return thread_svc.create_thread(visitor_session="sess-seq")


def test_seq_is_monotonic_across_turns():
    thread = _thread()
    seqs = []
    for i in range(5):
        message = ingest.ingest_inbound(
            thread.conversation, sender_kind="visitor", body=f"turn {i}", thread=thread
        )
        seqs.append(message.seq)
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "no two messages may share a seq"


def test_next_seq_starts_at_one():
    assert next_seq(_thread()) == 1


def test_latest_seq_tracks_the_highest():
    thread = _thread()
    for i in range(3):
        ingest.ingest_inbound(
            thread.conversation, sender_kind="visitor", body=f"t{i}", thread=thread
        )
    assert latest_seq(thread) == 3


def test_a_forward_jump_is_a_gap():
    gap = detect_gap(expected_seq=5, received_seq=8)
    assert gap is not None
    assert gap.size == 3


def test_a_duplicate_is_not_a_gap():
    """A lower seq means the client should DISCARD, not re-fetch."""
    assert detect_gap(expected_seq=5, received_seq=4) is None
    assert detect_gap(expected_seq=5, received_seq=5) is None


def test_resume_returns_only_what_was_missed():
    thread = _thread()
    for i in range(5):
        ingest.ingest_inbound(
            thread.conversation, sender_kind="visitor", body=f"turn {i}", thread=thread
        )
    payload = resume_payload(thread, last_acked_seq=2)
    assert payload["from_seq"] == 2
    assert payload["latest_seq"] == 5
    assert [m["seq"] for m in payload["messages"]] == [3, 4, 5]


def test_resume_from_zero_replays_everything():
    thread = _thread()
    for i in range(3):
        ingest.ingest_inbound(
            thread.conversation, sender_kind="visitor", body=f"t{i}", thread=thread
        )
    assert len(resume_payload(thread, 0)["messages"]) == 3


def test_a_turn_in_flight_is_never_lost():
    """
    It completes server-side and is available on the next fetch — that is what makes a
    dropped socket a display problem rather than a data-loss problem.
    """
    thread = _thread()
    message = ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body="completed anyway", thread=thread
    )
    assert message.id in [m.id for m in messages_since(thread, 0)]
