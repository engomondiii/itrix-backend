"""
The reported production transcript, replayed end to end (2026-08-07).

── WHAT WAS REPORTED ────────────────────────────────────────────────────────
A visitor went through the whole conversation — problem statement, "yes it will
be useful", "pressure is primarily on both, the scale is many", "Yes I would
like to move forward" — and the flow never ended with the governed email ask and
the personalised page. The reply at the acceptance turn instead promised that
"the itriX team is notified to reach out" and offered "a contact form" — a
notification that was never sent and a form that does not exist.

── WHY, IN THREE LAYERS ─────────────────────────────────────────────────────
1. The stop rule had no PROCEED signal. "Yes I would like to move forward" is
   explicit acceptance of the next step, but it matched none of decline /
   asked-for-outcome / asked-for-human, so the band stayed open, the contact ask
   (gated on DIAGNOSED) never fired, and the model improvised.
2. ``advance_on_turn`` returned early when ENABLE_ADAPTIVE_QUESTIONS was off —
   skipping the stop-rule evaluation AND the contact ask. With the flag off the
   band could never close at all, so even a volunteered email hit a permanent
   ``not_diagnosed`` and no page ever existed.
3. The question budget counted only generator emissions, so whenever emission
   stalled the band could not even close on exhaustion.

These tests replay the transcript verbatim and pin the fixed behaviour in both
flag states, plus the delivered-reply budget floor and the reveal-stash reset.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.models import Message, SenderKind
from apps.conversations.services import ingest, qualification, thread_state
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

# The visitor's side of the reported conversation, verbatim.
TRANSCRIPT = (
    "Our training and inference cost is rising faster than the value it creates.",
    "Yes it will be useful",
    "pressure is primarily is on both, the scale is many",
    "Yes I would like to move forward",
)
EMAIL_TURN = "My name is Fidel Omondi and my email is engomondiii@gmail.com"


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _agent_reply(thread, body="Understood — and one more question for you?"):
    """A delivered in-band reply, as the concierge produces between visitor turns."""
    return ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body=body, thread=thread
    )


def _replay(thread, *, with_replies: bool):
    for body in TRANSCRIPT:
        _visitor(thread, body)
        if with_replies:
            _agent_reply(thread)


# ─────────────────────────────────────────────────────────────────────────────
# The acceptance turn closes the band — the transcript's turning point
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_move_forward_closes_the_loop_and_asks_for_the_address():
    thread = thread_svc.create_thread(visitor_session="transcript-on")
    _replay(thread, with_replies=False)
    thread.refresh_from_db()

    # "Yes I would like to move forward" is acceptance: DIAGNOSED, on the visitor's
    # own signal — not stuck at IN_REVIEW waiting for two dimensions they were
    # never going to volunteer.
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    # And the SAME turn's reply must carry the governed ask: the decision was
    # stashed for the generation path, with the approved wording.
    decision = getattr(thread, "_contact_ask", None)
    assert decision and decision.get("ask") is True
    assert "email" in decision.get("text", "").lower()


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_email_after_acceptance_reveals_the_page():
    thread = thread_svc.create_thread(visitor_session="transcript-page")
    _replay(thread, with_replies=False)
    _visitor(thread, EMAIL_TURN)
    thread.refresh_from_db()

    reveal = getattr(thread, "_client_page_reveal", None)
    assert reveal and reveal.get("revealed") is True
    assert reveal.get("url") and "/c/" in reveal["url"]
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"
    # The lead carries the contact that was captured.
    assert thread.lead.email == "engomondiii@gmail.com"


# ─────────────────────────────────────────────────────────────────────────────
# The flag-off dead end, pinned shut
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=False, FRONTEND_WEB_URL="https://web.example")
def test_band_closes_and_page_reveals_with_adaptive_questions_off():
    """
    ENABLE_ADAPTIVE_QUESTIONS gates question GENERATION, not the journey. With it
    off, the same transcript must still close the band on the visitor's acceptance,
    still ask for the address, and still reveal the page when the address arrives.
    This was the hard dead end: the early return skipped the stop rule and the
    contact ask, so the thread sat at IN_REVIEW forever.
    """
    thread = thread_svc.create_thread(visitor_session="transcript-off")
    _replay(thread, with_replies=False)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    assert (getattr(thread, "_contact_ask", None) or {}).get("ask") is True

    _visitor(thread, EMAIL_TURN)
    thread.refresh_from_db()
    assert (getattr(thread, "_client_page_reveal", None) or {}).get("revealed") is True
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=False)
def test_suggest_next_stays_silent_with_the_flag_off():
    """The flag keeps exactly the scope its name claims: no generated chips."""
    thread = thread_svc.create_thread(visitor_session="transcript-chips")
    _visitor(thread, TRANSCRIPT[0])
    assert qualification.suggest_next(thread) == {}


# ─────────────────────────────────────────────────────────────────────────────
# The delivered-reply budget floor
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, QUESTION_BUDGET_PER_STATE=4)
def test_band_closes_on_delivered_reply_floor_when_emission_stalls():
    """
    A visitor who answers vaguely and never signals proceed must still leave the
    band once the budget's worth of replies has been delivered — even when the
    question generator emitted nothing (the counters it feeds stay at zero here
    because no suggestions are recorded).
    """
    thread = thread_svc.create_thread(visitor_session="floor-1")
    vague = ("hello there", "it is complicated", "hard to say", "maybe", "not sure")
    for body in vague:
        _visitor(thread, body)
        thread.refresh_from_db()
        if thread_state.current_state_key(thread) == "DIAGNOSED":
            break
        _agent_reply(thread)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    # Closed by exhaustion, not by coverage: nothing vague covered five dimensions.
    delivered = Message.objects.filter(thread=thread, sender_kind=SenderKind.AGENT).count()
    assert delivered >= 4


def test_questions_asked_floors_at_delivered_agent_replies():
    thread = thread_svc.create_thread(visitor_session="floor-2")
    _visitor(thread, "hello")
    for _ in range(3):
        _agent_reply(thread)
    assert qualification._questions_asked(thread) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# The reveal stash resets, socket-lifetime instance included
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_stash_clears_on_the_turn_after_the_reveal():
    """
    The WebSocket consumer reuses ONE Thread instance for the socket's life. The
    reveal stashed on the turn that fired it must be cleared on the next turn, or
    the reveal directive and the appended link repeat under every later reply.
    """
    thread = thread_svc.create_thread(visitor_session="stash-1")
    _replay(thread, with_replies=False)
    _visitor(thread, EMAIL_TURN)
    assert (getattr(thread, "_client_page_reveal", None) or {}).get("revealed") is True

    # Same instance, next turn — exactly the consumer's situation.
    _visitor(thread, "thank you, this looks great")
    assert getattr(thread, "_client_page_reveal", None) is None
