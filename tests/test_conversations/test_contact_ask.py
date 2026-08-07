"""
The contact ask — the stage that carries a closed review to the personalised page.

The bug these cover: ``reveal_bridge`` gates the page on an email address, and
nothing in the system ever asked for one. A conversation reached DIAGNOSED and sat
there, while the model — given no instruction — promised a human follow-up.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.services import (
    contact_ask,
    ingest,
    qualification,
    reveal_bridge,
    thread_state,
)
from apps.conversations.services import threads as thread_svc

# Covers workload + pressure_area + platform_environment in one turn, which is the
# required set for the band — so the loop closes and the thread reaches DIAGNOSED.
# Covers the FIVE required dimensions in one turn — workload, pressure_area,
# platform_environment, scale and timeline — so the loop closes and the thread reaches
# DIAGNOSED. It grew when the requirement went from three dimensions to five (#12);
# a single sentence covering three no longer closes the loop, which is the point of
# that change.
COVERING_TEXT = (
    "Our training and inference workload runs on a GPU cluster with PyTorch and the "
    "cost is rising faster than the value it creates. We run 64 GPUs and it is urgent "
    "this quarter."
)


def _thread():
    return thread_svc.create_thread(visitor_session="contact-ask-session", title="")


def _say(thread, body: str):
    message = ingest.ingest_inbound(
        thread.conversation, sender_kind="visitor", body=body, thread=thread
    )
    thread.refresh_from_db()
    return message


# ── the gates ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_no_ask_before_the_loop_closes():
    """Value first: nothing is asked for until the diagnosis has been delivered."""
    thread = _thread()
    _say(thread, "Our costs are rising.")

    decision = contact_ask.evaluate(thread, "Our costs are rising.")

    assert decision["ask"] is False
    assert decision["reason"] == contact_ask.NOT_DIAGNOSED


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_ask_fires_once_the_loop_closes():
    """This is the failing case: DIAGNOSED, no address, and previously no ask."""
    thread = _thread()
    _say(thread, COVERING_TEXT)

    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    decision = contact_ask.evaluate(thread, "")

    assert decision["ask"] is True
    assert decision["reason"] == contact_ask.ASK
    assert "email" in decision["text"].lower()


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_ask_when_the_current_turn_carries_the_address():
    """
    The reveal acts on the address in this same turn, so asking would be noise.

    Evaluated with the address in ``body`` rather than already ingested, which is
    exactly the ordering the turn path uses: the decision is taken while the reveal
    is still deciding, and the two must not disagree about whether we have one.
    """
    thread = _thread()
    _say(thread, COVERING_TEXT)

    decision = contact_ask.evaluate(thread, "Sure — it is dana@example.com")

    assert decision["ask"] is False
    assert decision["reason"] == contact_ask.EMAIL_ALREADY_GIVEN


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_ask_is_budgeted_and_then_stops():
    """A third ask would be pressure. Two, and then we let it go."""
    thread = _thread()
    _say(thread, COVERING_TEXT)

    for expected in range(contact_ask.DEFAULT_CONTACT_ASK_BUDGET):
        decision = contact_ask.evaluate(thread, "")
        assert decision["ask"] is True, f"ask {expected + 1} should be allowed"
        contact_ask.record_asked(thread, decision)

    exhausted = contact_ask.evaluate(thread, "")
    assert exhausted["ask"] is False
    assert exhausted["reason"] == contact_ask.BUDGET_EXHAUSTED


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_second_ask_offers_a_way_out():
    """Declining has to be a real option, or the ask is a demand."""
    thread = _thread()
    _say(thread, COVERING_TEXT)

    first = contact_ask.evaluate(thread, "")
    contact_ask.record_asked(thread, first)
    second = contact_ask.evaluate(thread, "")

    assert second["text"] != first["text"]
    assert "rather not" in second["text"].lower()


@pytest.mark.django_db
def test_an_unseen_ask_does_not_spend_the_budget():
    """An ask held by the guard was never put to anybody."""
    thread = _thread()
    _say(thread, COVERING_TEXT)

    contact_ask.record_asked(thread, {"ask": False, "text": "not asked"})

    assert contact_ask.asks_made(thread) == 0


# ── the guarantee ────────────────────────────────────────────────────────────


def test_the_approved_wording_is_appended_when_the_reply_does_not_ask():
    decision = {"ask": True, "text": "What is your work email address?"}

    out = contact_ask.append_ask("Here is what that suggests.", decision)

    assert out.endswith("What is your work email address?")


def test_the_approved_wording_is_not_appended_twice():
    """The model was told to ask in its own words; do not ask underneath it."""
    decision = {"ask": True, "text": "What is your work email address?"}

    out = contact_ask.append_ask(
        "Happy to put that together — what email should I use?", decision
    )

    assert out.count("email") == 1


def test_nothing_is_appended_when_no_ask_is_due():
    assert contact_ask.append_ask("A reply.", {"ask": False}) == "A reply."


def test_the_directive_forbids_the_ending_that_caused_this_bug():
    directive = contact_ask.directive({"ask": True, "text": "..."})

    assert "be in touch" in directive
    assert "email address" in directive


def test_no_directive_when_no_ask_is_due():
    assert contact_ask.directive({"ask": False}) == ""


# ── the wiring ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_turn_path_stashes_the_decision_for_the_agent():
    """
    ``advance_on_turn`` must leave the decision where ``build_turn_extra`` finds it,
    or the agent is never told to ask.
    """
    from apps.conversations.services import conversation_context

    thread = _thread()
    _say(thread, COVERING_TEXT)

    qualification.advance_on_turn(thread, COVERING_TEXT)
    extra = conversation_context.build_turn_extra(thread, COVERING_TEXT)

    assert extra.get("contact_ask", {}).get("ask") is True


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_agent_prompt_carries_the_instruction_to_ask():
    from apps.agents.services.concierge import ConciergeAgent
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext

    thread = _thread()
    _say(thread, COVERING_TEXT)
    qualification.advance_on_turn(thread, COVERING_TEXT)

    from apps.conversations.services import conversation_context

    ctx = AgentContext(
        lead_id=None,
        prompt=COVERING_TEXT,
        plane=PLANE_PUBLIC,
        context_label="anonymous_review",
        extra=conversation_context.build_turn_extra(thread, COVERING_TEXT),
    )
    prompt = ConciergeAgent()._conversation_user_prompt(ctx, COVERING_TEXT, "INSTRUCTION")

    assert "work email address" in prompt
    assert "be in touch" in prompt


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_a_revealed_page_is_handed_over_instead_of_asked_about():
    """The two directives are mutually exclusive; the reveal wins."""
    from apps.agents.services.concierge import ConciergeAgent

    directive = ConciergeAgent()._reveal_directive(
        {"client_page_reveal": {"revealed": True, "url": "https://example.test/c/tok"}}
    )

    assert "READY NOW" in directive


# ── end to end ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.test")
def test_the_conversation_can_now_reach_the_personalised_page():
    """
    The whole point. Before this stage existed the thread stopped at DIAGNOSED with
    ``no_email_yet`` forever, because nothing asked. Now: loop closes, we ask, the
    visitor answers, the page is revealed.
    """
    thread = _thread()

    _say(thread, COVERING_TEXT)
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    assert reveal_bridge.maybe_reveal_client_page(thread, "")["reason"] == "no_email_yet"

    # The reply for that turn now carries an ask.
    assert contact_ask.evaluate(thread, "")["ask"] is True

    # The visitor answers it. The reveal fires inside that same turn, so the page
    # exists by the time the reply for it is generated.
    _say(thread, "dana@example.com")

    assert thread.lead is not None
    assert thread.lead.email == "dana@example.com"
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"
    assert reveal_bridge._client_page_url("tok").startswith("https://web.test/c/")


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_the_ask_does_not_survive_the_turn_that_reveals_the_page():
    """
    The WebSocket consumer reuses ONE Thread instance for the whole socket, so a
    decision left over from an earlier turn would still be there on the turn that
    reveals the page — and the reply would hand over the personalised page and then
    ask for the address it had just used.
    """
    from apps.conversations.services import conversation_context

    thread = _thread()
    # ``_say`` ingests, and ingest is the single production call site of
    # ``advance_on_turn`` — one call per visitor turn is the contract, and the
    # stash-reset semantics (always assigned, per turn) depend on it. A second
    # manual call here would model a transport that does not exist and would
    # (correctly) read as a new turn, clearing the reveal it just made.
    _say(thread, COVERING_TEXT)
    assert getattr(thread, "_contact_ask", None) is not None  # asked on this turn

    # Same instance, next turn — and this one carries the address.
    _say(thread, "dana@example.com")
    extra = conversation_context.build_turn_extra(thread, "dana@example.com")

    assert getattr(thread, "_contact_ask", None) is None
    assert "contact_ask" not in extra
    assert extra.get("client_page_reveal", {}).get("revealed") is True


@pytest.mark.django_db
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_ask_once_the_thread_has_a_lead():
    """A revealed thread already gave us the address; never ask again."""
    thread = _thread()
    _say(thread, COVERING_TEXT)
    _say(thread, "dana@example.com")
    reveal_bridge.maybe_reveal_client_page(thread, "dana@example.com")
    thread.refresh_from_db()

    decision = contact_ask.evaluate(thread, "")

    assert decision["ask"] is False
    assert decision["reason"] == contact_ask.ALREADY_HAS_LEAD
