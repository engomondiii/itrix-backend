"""
The second reported transcript, replayed end to end (2026-08-10).

── WHAT WAS REPORTED ────────────────────────────────────────────────────────
After the first chat-flow fix shipped, the flow reached the page — but the ask
was wrong. At the acceptance turn ("Yes please") the model asked "what name or
organisation should it be addressed to?" and a visitor who answered exactly that
got nothing, because the reveal is email-anchored. Two causes:

1. "Yes please" — the most common acceptance shape — matched no PROCEED pattern,
   so the band was still open at that turn, the governed ask (gated on
   DIAGNOSED) could not fire, and the model improvised the ask, choosing the
   one detail the reveal cannot use.
2. The governed copy itself asked for the address alone, so even when it did
   fire nothing ever named the organisation the user wants collected with it.

The fixes: bare assent (guarded) closes the band; the governed ask and the
directive name BOTH details with the email stated as the essential one; and the
"Org, email" answer shape is captured onto the Lead.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.models import SenderKind
from apps.conversations.services import contact_ask, ingest, reveal_bridge, thread_state
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

# The visitor's side of the reported conversation, verbatim.
TRANSCRIPT = (
    "Our training and inference cost is rising faster than the value it creates.",
    "Yes it would help",
    "Yes please",
)
EMAIL_TURN = "engomondiii@gmail.com"


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _agent_reply(thread, body="Here is how the engagement works — shall we continue?"):
    return ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body=body, thread=thread
    )


def _replay(thread):
    """The reported conversation with a delivered reply after each turn."""
    for body in TRANSCRIPT:
        _visitor(thread, body)
        thread.refresh_from_db()
        if thread_state.current_state_key(thread) in ("ARRIVED", "IN_REVIEW"):
            _agent_reply(thread)


# ─────────────────────────────────────────────────────────────────────────────
# "Yes please" is acceptance: the band closes THERE, and the ask names both
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_yes_please_closes_the_band_and_the_ask_names_both_details():
    thread = thread_svc.create_thread(visitor_session="t2-accept")
    _replay(thread)
    thread.refresh_from_db()

    # The acceptance turn ends the band — not two turns later on budget.
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    # And the governed ask for that same reply names BOTH details, with the
    # email as the essential one — never the organisation alone.
    decision = getattr(thread, "_contact_ask", None)
    assert decision and decision.get("ask") is True
    text = decision.get("text", "").lower()
    assert "email" in text
    assert "organisation" in text


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_informational_assent_does_not_close_the_band():
    """
    "Yes it would help" accepts a walkthrough, not the engagement — the
    substantive words disqualify it from bare assent, so the band stays open
    and the walkthrough is delivered before anything is asked for.
    """
    thread = thread_svc.create_thread(visitor_session="t2-info")
    _visitor(thread, TRANSCRIPT[0])
    _agent_reply(thread)
    _visitor(thread, "Yes it would help")
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_bare_assent_on_the_first_turn_does_not_close_the_band():
    """An acceptance needs an offer to accept; turn one has had none."""
    thread = thread_svc.create_thread(visitor_session="t2-first")
    _visitor(thread, "yes")
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


# ─────────────────────────────────────────────────────────────────────────────
# The email completes it; the organisation alone never does
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_email_after_the_ask_reveals_the_page():
    thread = thread_svc.create_thread(visitor_session="t2-email")
    _replay(thread)
    _visitor(thread, EMAIL_TURN)
    thread.refresh_from_db()

    reveal = getattr(thread, "_client_page_reveal", None)
    assert reveal and reveal.get("revealed") is True
    assert reveal.get("url") and "/c/" in reveal["url"]
    assert thread.lead_id is not None
    assert thread.lead.email == "engomondiii@gmail.com"
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_organisation_alone_re_asks_for_the_email_instead_of_dead_air():
    """
    The reported dead end: the visitor answered the (improvised) organisation
    question and nothing happened. Now an organisation-only reply keeps the
    thread alive — no reveal (email-anchored, unchanged), and the SECOND
    governed ask fires so the reply asks for the email specifically.
    """
    thread = thread_svc.create_thread(visitor_session="t2-orgonly")
    _replay(thread)
    # The transport records the ask when the reply that carries it is DELIVERED
    # (an ask nobody saw must not consume the budget). This replay has no
    # transport, so record ask one the way views_thread / the consumer do.
    contact_ask.record_asked(thread, getattr(thread, "_contact_ask", None))
    _visitor(thread, "GPSLAB")
    thread.refresh_from_db()

    assert getattr(thread, "_client_page_reveal", None) is None
    assert thread.lead_id is None
    decision = getattr(thread, "_contact_ask", None)
    assert decision and decision.get("ask") is True
    assert decision.get("asks_made") == 1  # this is ask two of two

    # And the email on the next turn still completes the flow.
    _visitor(thread, EMAIL_TURN)
    thread.refresh_from_db()
    assert (getattr(thread, "_client_page_reveal", None) or {}).get("revealed") is True


# ─────────────────────────────────────────────────────────────────────────────
# The combined answer shape is captured onto the Lead
# ─────────────────────────────────────────────────────────────────────────────
def test_org_comma_email_answer_is_captured():
    c = reveal_bridge.extract_contact_from_text("GPSLAB, engomondiii@gmail.com")
    assert c["email"] == "engomondiii@gmail.com"
    assert c["company"] == "GPSLAB"


@pytest.mark.parametrize("text", ["Sure, engomondiii@gmail.com", "Thanks, x@y.com", "engomondiii@gmail.com"])
def test_courtesy_openers_are_not_captured_as_an_organisation(text):
    assert reveal_bridge.extract_contact_from_text(text)["company"] == ""


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_combined_answer_reveals_with_the_organisation_on_the_lead():
    thread = thread_svc.create_thread(visitor_session="t2-combined")
    _replay(thread)
    _visitor(thread, "GPSLAB, engomondiii@gmail.com")
    thread.refresh_from_db()

    assert (getattr(thread, "_client_page_reveal", None) or {}).get("revealed") is True
    assert thread.lead.email == "engomondiii@gmail.com"
    assert thread.lead.company == "GPSLAB"
