"""
The conversation -> client-page reveal bridge (states 3 -> 4), corrected.

Proves the two fixes over the first version:
  * contact is ACCUMULATED across turns, so a name+email in one message and a
    company in another combine (the exact failure seen in production);
  * the trigger is EMAIL-ANCHORED — an email alone reveals the page; a company is
    captured when present but never required.

Plus: the agent is told to present the page in its own words when a reveal fires.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.models import SenderKind
from apps.conversations.services import ingest, reveal_bridge, thread_state
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

COVERING_TEXT = (
    "Our training and inference workload runs on PyTorch with CUDA and it is too "
    "slow, and the cost has become a real problem for us."
)


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


# ─────────────────────────────────────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────────────────────────────────────
def test_extracts_name_and_email_without_trailing_connector():
    c = reveal_bridge.extract_contact_from_text(
        "My name is Fidel Omondi and my email is engomondiii@gmail.com"
    )
    assert c["email"] == "engomondiii@gmail.com"
    assert c["name"] == "Fidel Omondi"  # not "Fidel Omondi and"
    assert c["company"] == ""


def test_extracts_company():
    c = reveal_bridge.extract_contact_from_text("Our company is GPSLAB")
    assert c["company"] == "GPSLAB"


def test_accumulated_contact_merges_across_turns():
    thread = thread_svc.create_thread(visitor_session="acc-1")
    _visitor(thread, "My name is Fidel Omondi and my email is engomondiii@gmail.com")
    _visitor(thread, "Our company is GPSLAB")
    merged = reveal_bridge.accumulated_contact(thread)
    # Both pieces recovered even though each was in a different message.
    assert merged["email"] == "engomondiii@gmail.com"
    assert merged["company"] == "GPSLAB"
    assert merged["name"] == "Fidel Omondi"


# ─────────────────────────────────────────────────────────────────────────────
# The production failure, reproduced and fixed: contact split across turns
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_fires_when_email_given_without_company():
    thread = thread_svc.create_thread(visitor_session="split-1")
    _visitor(thread, COVERING_TEXT)  # -> DIAGNOSED
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    # Email given, NO company — this used to fail. It must reveal now.
    _visitor(thread, "My name is Fidel Omondi and my email is engomondiii@gmail.com")
    thread.refresh_from_db()
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "CLIENT_PAGE"

    from apps.leads.models import Lead

    lead = Lead.objects.get(id=thread.lead_id)
    assert lead.email == "engomondiii@gmail.com"
    assert lead.visitor_name == "Fidel Omondi"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_fires_with_company_in_a_later_turn():
    thread = thread_svc.create_thread(visitor_session="split-2")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()

    # Company FIRST (no email) — should NOT reveal yet (no email to anchor).
    _visitor(thread, "Our company is GPSLAB")
    thread.refresh_from_db()
    # (may or may not have revealed; it must not, because there's no email)
    assert thread.lead_id is None

    # Then email — now it reveals, and the company from the earlier turn is captured.
    _visitor(thread, "my email is engomondiii@gmail.com")
    thread.refresh_from_db()
    assert thread.lead_id is not None
    from apps.leads.models import Lead

    lead = Lead.objects.get(id=thread.lead_id)
    assert lead.company == "GPSLAB"  # accumulated from the earlier turn


# ─────────────────────────────────────────────────────────────────────────────
# Gating
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_reveal_before_diagnosed():
    thread = thread_svc.create_thread(visitor_session="gate-1")
    _visitor(thread, "my email is a@b.com")
    thread.refresh_from_db()
    out = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")
    assert out["revealed"] is False
    assert out["reason"] == "not_diagnosed"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_no_reveal_without_email():
    thread = thread_svc.create_thread(visitor_session="gate-2")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    out = reveal_bridge.maybe_reveal_client_page(thread, "our company is Acme")
    assert out["revealed"] is False
    assert out["reason"] == "no_email_yet"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_reveal_is_idempotent():
    thread = thread_svc.create_thread(visitor_session="idem-1")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    first = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")
    assert first["revealed"] is True
    thread.refresh_from_db()
    second = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")
    assert second["revealed"] is False
    assert second["reason"] == "already_has_lead"


# ─────────────────────────────────────────────────────────────────────────────
# Token validity + AI directive
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_token_is_valid_client_page_token():
    thread = thread_svc.create_thread(visitor_session="tok-1")
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    out = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")

    from apps.journey.services.capability_token import TOKEN_CLIENT_PAGE, verify

    payload = verify(out["token"], expected_typ=TOKEN_CLIENT_PAGE)
    assert payload.state == "CLIENT_PAGE"
    assert payload.sub == str(thread.lead_id)


def test_agent_directive_present_on_reveal():
    from apps.agents.services.concierge import ConciergeAgent
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext

    agent = ConciergeAgent()
    ctx = AgentContext(
        plane=PLANE_PUBLIC,
        context_label="anonymous_review",
        extra={
            "message": "ok",
            "recent_turns": ["Visitor: hi", "itriX: hello"],
            "journey_state": "CLIENT_PAGE",
            "client_page_reveal": {"revealed": True, "url": "https://web.example/c/TOK"},
        },
    )
    prompt = agent._conversation_user_prompt(ctx, "ok", "INSTR")
    assert "HAS JUST BEEN GENERATED" in prompt
    assert "https://web.example/c/TOK" in prompt
    # It explicitly forbids the "be in touch" ending.
    assert "be in touch" in prompt


def test_agent_directive_absent_without_reveal():
    from apps.agents.services.concierge import ConciergeAgent
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext

    agent = ConciergeAgent()
    ctx = AgentContext(
        plane=PLANE_PUBLIC,
        context_label="anonymous_review",
        extra={"message": "ok", "recent_turns": ["Visitor: hi"], "journey_state": "IN_REVIEW"},
    )
    prompt = agent._conversation_user_prompt(ctx, "ok", "INSTR")
    assert "HAS JUST BEEN GENERATED" not in prompt
