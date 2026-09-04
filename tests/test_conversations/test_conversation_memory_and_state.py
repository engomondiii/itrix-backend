"""Conversation memory plus explicit relationship/journey-state orchestration.

The numbered qualification ladder is no longer opened by an arbitrary anonymous turn.
Visitors and Technical Evaluators may remain at ARRIVED indefinitely.  A concrete workload
evaluation request first creates an explicit mode-change offer; only consent enters the
Customer/Strategic Customer qualification band.  Once in that band, the existing deterministic
coverage/stop-rule/question machinery still owns IN_REVIEW -> DIAGNOSED.
"""

from __future__ import annotations

import pytest

from apps.conversations.models import SenderKind
from apps.conversations.services import (
    conversation_context,
    ingest,
    qualification,
    thread_state,
)
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db


# A single sentence that covers all three required band dimensions:
#   workload             -> "training", "inference", "workload"
#   platform_environment -> "PyTorch", "CUDA"
#   pressure_area        -> "slow", "cost"
# Covers all FIVE required dimensions — workload, pressure_area,
# platform_environment, scale and timeline — so the loop closes in one turn.
# Widened when #12 raised the requirement from three dimensions to five.
COVERING_TEXT = (
    "Our training and inference workload runs on a GPU cluster with PyTorch and the "
    "cost is rising faster than the value it creates. We run 64 GPUs and it is urgent "
    "this quarter."
)


def _persist_visitor(thread, body: str):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _prime_customer(thread):
    """Enter the already-consented Customer lane for qualification-loop unit tests."""
    thread.relationship_state = "customer"
    thread.mode_change_status = "consented"
    thread.mirror_status = "pending"
    thread.save(update_fields=["relationship_state", "mode_change_status", "mirror_status"])
    thread.refresh_from_db()


# ─────────────────────────────────────────────────────────────────────────────
# 1. MEMORY
# ─────────────────────────────────────────────────────────────────────────────
def test_recent_turns_include_prior_visitor_and_agent_turns():
    thread = thread_svc.create_thread(visitor_session="mem-1")
    _persist_visitor(thread, "We run large training jobs.")
    ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body="Understood — tell me more.", thread=thread
    )

    turns = conversation_context.recent_turns(thread)
    assert any("We run large training jobs." in t for t in turns)
    assert any("Understood" in t for t in turns)
    # Speaker labels are present so the model can tell who said what.
    assert any(t.startswith("Visitor:") for t in turns)
    assert any(t.startswith("itriX:") for t in turns)


def test_build_turn_extra_carries_memory_and_state():
    thread = thread_svc.create_thread(visitor_session="mem-2")
    _persist_visitor(thread, "First message about our solver.")

    extra = conversation_context.build_turn_extra(thread, "second message")
    assert extra["message"] == "second message"
    assert extra["thread_id"] == str(thread.id)
    # The prior turn is available as memory; the current message is passed separately.
    assert any("solver" in t for t in extra["recent_turns"])
    assert "journey_state" in extra


def test_recent_turns_excludes_the_current_message():
    thread = thread_svc.create_thread(visitor_session="mem-3")
    msg = _persist_visitor(thread, "the only turn so far")

    # Excluding the just-persisted turn leaves no prior turns to replay.
    turns = conversation_context.recent_turns(thread, exclude_message_id=str(msg.id))
    assert all("the only turn so far" not in t for t in turns)


# ─────────────────────────────────────────────────────────────────────────────
# 2. STATE — anonymous threads advance without a lead
# ─────────────────────────────────────────────────────────────────────────────
def test_anonymous_thread_starts_at_arrived():
    thread = thread_svc.create_thread(visitor_session="state-1")
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert thread_state.current_state_number(thread) == 1


def test_an_ordinary_anonymous_turn_stays_at_arrived():
    thread = thread_svc.create_thread(visitor_session="state-2")
    _persist_visitor(thread, "Hello, we have a compute question.")

    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert thread.relationship_state == "visitor"


def test_concrete_evaluation_request_offers_mode_change_before_customer_state():
    thread = thread_svc.create_thread(visitor_session="state-2b")
    _persist_visitor(thread, "Our inference workload is expensive. Please evaluate the bottleneck.")

    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert thread.relationship_state == "visitor"
    assert thread.mode_change_status == "offered"
    assert thread.mode_change_target == "customer"

    _persist_visitor(thread, "Yes, proceed.")
    thread.refresh_from_db()
    assert thread.relationship_state == "customer"
    assert thread.mode_change_status == "consented"
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


def test_state_only_moves_forward():
    thread = thread_svc.create_thread(visitor_session="state-3")
    thread_state.enter_in_review(thread)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "IN_REVIEW"
    # Calling the first-turn transition again does not reset to ARRIVED.
    thread_state.enter_in_review(thread)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


def test_str03_confirm_allows_recommendation_only_after_confirmation():
    from apps.conversations.services import engagement_state

    thread = thread_svc.create_thread(visitor_session="mirror-confirm")
    _prime_customer(thread)
    assert engagement_state.recommendation_allowed(thread) is False

    _persist_visitor(thread, "This reflects my situation")
    thread.refresh_from_db()

    assert thread.mirror_status == engagement_state.MIRROR_CONFIRMED
    assert engagement_state.recommendation_allowed(thread) is True
    assert any(e.get("event") == "problem_mirror_confirmed" for e in thread.consent_history)


def test_str03_refine_keeps_recommendation_gate_closed():
    from apps.conversations.services import engagement_state

    thread = thread_svc.create_thread(visitor_session="mirror-refine")
    _prime_customer(thread)
    _persist_visitor(thread, "Refine this")
    thread.refresh_from_db()

    assert thread.mirror_status == engagement_state.MIRROR_REFINE
    assert engagement_state.recommendation_allowed(thread) is False
    assert any(e.get("event") == "problem_mirror_refine_requested" for e in thread.consent_history)


def test_str03_start_again_keeps_recommendation_gate_closed():
    from apps.conversations.services import engagement_state

    thread = thread_svc.create_thread(visitor_session="mirror-restart")
    _prime_customer(thread)
    _persist_visitor(thread, "Start again")
    thread.refresh_from_db()

    assert thread.mirror_status == engagement_state.MIRROR_RESTART
    assert engagement_state.recommendation_allowed(thread) is False
    assert any(e.get("event") == "problem_mirror_restart_requested" for e in thread.consent_history)


# ─────────────────────────────────────────────────────────────────────────────
# 3. LOOP END — the qualification loop closes when the band is covered
# ─────────────────────────────────────────────────────────────────────────────
def test_loop_closes_when_band_is_covered(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    thread = thread_svc.create_thread(visitor_session="loop-1")
    _prime_customer(thread)

    # One turn that covers all required dimensions at once.
    _persist_visitor(thread, COVERING_TEXT)
    qualification.advance_on_turn(thread, COVERING_TEXT)

    thread.refresh_from_db()
    # Band satisfied -> loop closed -> DIAGNOSED (3).
    assert thread_state.current_state_key(thread) == "DIAGNOSED"


def test_loop_stays_open_when_band_not_covered(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    thread = thread_svc.create_thread(visitor_session="loop-2")
    _prime_customer(thread)

    # A vague turn that covers nothing required.
    _persist_visitor(thread, "Hi there, just looking around.")
    qualification.advance_on_turn(thread, "Hi there, just looking around.")

    thread.refresh_from_db()
    # Still in the band — not closed.
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


def test_visitor_asking_for_a_human_closes_the_loop(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    thread = thread_svc.create_thread(visitor_session="loop-3")
    _prime_customer(thread)

    text = "Can I just speak to a real person about this?"
    _persist_visitor(thread, text)
    qualification.advance_on_turn(thread, text)

    thread.refresh_from_db()
    # The stop rule ends the loop for "asked for a human" even with nothing covered.
    assert thread_state.current_state_key(thread) == "DIAGNOSED"


# ─────────────────────────────────────────────────────────────────────────────
# 4. NEXT — a follow-up question is suggested while open, and not after close
# ─────────────────────────────────────────────────────────────────────────────
def test_next_prompt_suggested_while_loop_open(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    thread = thread_svc.create_thread(visitor_session="next-1")
    _prime_customer(thread)

    _persist_visitor(thread, "We do a lot of training.")
    qualification.advance_on_turn(thread, "We do a lot of training.")

    payload = qualification.suggest_next(thread)
    # A follow-up question was produced (from the approved bank at minimum).
    assert payload
    assert payload.get("primary")
    assert payload.get("thread_id") == str(thread.id)


def test_no_suggestion_after_loop_closes(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    thread = thread_svc.create_thread(visitor_session="next-2")
    _prime_customer(thread)

    _persist_visitor(thread, COVERING_TEXT)
    qualification.advance_on_turn(thread, COVERING_TEXT)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    # Loop is closed -> nothing more is suggested.
    payload = qualification.suggest_next(thread)
    assert payload == {}


# ─────────────────────────────────────────────────────────────────────────────
# Shell contract reflects the real anonymous state
# ─────────────────────────────────────────────────────────────────────────────
def test_anonymous_shell_reports_real_state_and_loop(settings):
    settings.ENABLE_ADAPTIVE_QUESTIONS = True
    from apps.journey.services import shell

    thread = thread_svc.create_thread(visitor_session="shell-1")

    # Fresh thread: state 1, loop open.
    contract = shell.for_anonymous_thread(thread)
    assert contract["journey_state"] == 1
    assert contract["question_loop_open"] is True

    # After explicit Customer entry and a covering turn the loop closes.
    _prime_customer(thread)
    _persist_visitor(thread, COVERING_TEXT)
    qualification.advance_on_turn(thread, COVERING_TEXT)
    thread.refresh_from_db()

    contract = shell.for_anonymous_thread(thread)
    assert contract["journey_state"] == 3
    assert contract["question_loop_open"] is False
    assert contract["value_delivered"] is True
