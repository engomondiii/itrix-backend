"""
The conversation -> client-page reveal bridge (states 3 -> 4).

Proves the behaviour that was missing: once the qualification loop has closed
(DIAGNOSED) and the visitor gives a company + a valid email, the conversation
creates a Lead, advances to CLIENT_PAGE, mints a valid client-page token, and
hands the visitor a /c/<token> link — so the journey reaches the reveal instead
of stopping at DIAGNOSED.
"""

from __future__ import annotations

import re

import pytest
from django.test import override_settings

from apps.conversations.models import SenderKind
from apps.conversations.services import (
    ingest,
    reveal_bridge,
    thread_state,
)
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

COVERING_TEXT = (
    "Our training and inference workload runs on PyTorch with CUDA and it is too "
    "slow, and the cost has become a real problem for us."
)
CONTACT_TEXT = "Yes, my company is GPSLAB and my contact email is engomondiii@gmail.com"


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


# ─────────────────────────────────────────────────────────────────────────────
# Contact extraction
# ─────────────────────────────────────────────────────────────────────────────
def test_extract_contact_pulls_company_and_email():
    c = reveal_bridge.extract_contact(CONTACT_TEXT)
    assert c["email"] == "engomondiii@gmail.com"
    assert c["company"] == "GPSLAB"


def test_extract_contact_rejects_malformed_email():
    c = reveal_bridge.extract_contact("my company is Acme and email is not-an-email")
    assert c["email"] == ""


def test_extract_contact_empty_on_blank():
    assert reveal_bridge.extract_contact("") == {"email": "", "company": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Reveal gating
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_reveal_before_diagnosed():
    thread = thread_svc.create_thread(visitor_session="gate-1")
    # Contact given, but the loop has not closed yet (still ARRIVED/IN_REVIEW).
    _visitor(thread, CONTACT_TEXT)
    thread.refresh_from_db()
    out = reveal_bridge.maybe_reveal_client_page(thread, CONTACT_TEXT)
    assert out["revealed"] is False
    assert thread.lead_id is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_reveal_without_contact():
    thread = thread_svc.create_thread(visitor_session="gate-2")
    _visitor(thread, COVERING_TEXT)  # closes loop -> DIAGNOSED
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    # A turn with no contact does not reveal.
    out = reveal_bridge.maybe_reveal_client_page(thread, "tell me more about pricing")
    assert out["revealed"] is False
    assert out["reason"] == "contact_incomplete"


# ─────────────────────────────────────────────────────────────────────────────
# The full reveal
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_creates_lead_and_advances_to_client_page():
    thread = thread_svc.create_thread(visitor_session="reveal-1")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    out = reveal_bridge.maybe_reveal_client_page(thread, CONTACT_TEXT)
    assert out["revealed"] is True
    assert out["token"]
    assert out["url"].startswith("https://web.example/c/")

    thread.refresh_from_db()
    # Thread now bound to a lead and at CLIENT_PAGE.
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"

    from apps.leads.models import Lead

    lead = Lead.objects.get(id=thread.lead_id)
    assert lead.company == "GPSLAB"
    assert lead.email == "engomondiii@gmail.com"
    assert lead.lead_source == "conversation"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_revealed_token_is_a_valid_client_page_token():
    thread = thread_svc.create_thread(visitor_session="reveal-2")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    out = reveal_bridge.maybe_reveal_client_page(thread, CONTACT_TEXT)

    from apps.journey.services.capability_token import TOKEN_CLIENT_PAGE, verify

    payload = verify(out["token"], expected_typ=TOKEN_CLIENT_PAGE)
    assert payload.typ == TOKEN_CLIENT_PAGE
    assert payload.state == "CLIENT_PAGE"
    # The token is bound to the created lead.
    assert payload.sub == str(thread.lead_id)


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_is_idempotent():
    thread = thread_svc.create_thread(visitor_session="reveal-3")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    first = reveal_bridge.maybe_reveal_client_page(thread, CONTACT_TEXT)
    assert first["revealed"] is True
    thread.refresh_from_db()
    # A second contact turn does not create a second lead / re-reveal.
    second = reveal_bridge.maybe_reveal_client_page(thread, CONTACT_TEXT)
    assert second["revealed"] is False
    assert second["reason"] == "already_has_lead"


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end through the turn path
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_full_turn_path_reveals_and_links():
    thread = thread_svc.create_thread(visitor_session="e2e-x")
    _visitor(thread, COVERING_TEXT)  # -> DIAGNOSED via ingest hook
    thread.refresh_from_db()

    # The contact turn goes through ingest, which runs advance_on_turn -> reveal.
    _visitor(thread, CONTACT_TEXT)
    thread.refresh_from_db()
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"
