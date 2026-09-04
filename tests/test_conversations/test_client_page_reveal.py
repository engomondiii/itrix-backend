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

# Covers all FIVE required dimensions — workload, pressure_area,
# platform_environment, scale and timeline — so the loop closes in one turn.
# Widened when #12 raised the requirement from three dimensions to five.
COVERING_TEXT = (
    "Our training and inference workload runs on a GPU cluster with PyTorch and the "
    "cost is rising faster than the value it creates. We run 64 GPUs and it is urgent "
    "this quarter."
)


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _prime_confirmed_customer(thread):
    """Put this bridge unit test at the legitimate post-STR-03 review-start boundary."""
    thread.relationship_state = "customer"
    thread.mirror_status = "confirmed"
    thread.identity_needed_action = "formal_evaluation"
    thread.selected_action = "start_controlled_evaluation"
    thread.save(
        update_fields=[
            "relationship_state",
            "mirror_status",
            "identity_needed_action",
            "selected_action",
        ]
    )
    thread_state._mirror_onto_thread(thread, "DIAGNOSED")
    thread.refresh_from_db()


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
def test_review_starts_when_email_given_without_company(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="split-1")
    _visitor(thread, COVERING_TEXT)
    _prime_confirmed_customer(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )

    out = reveal_bridge.maybe_reveal_client_page(
        thread, "My name is Fidel Omondi and my email is engomondiii@gmail.com"
    )
    thread.refresh_from_db()

    assert out["revealed"] is False
    assert out["reason"] == "review_preparing"
    assert out["token"] is None and out["url"] is None
    assert thread.lead_id is not None
    assert thread_state.current_state_key(thread) == "DIAGNOSED"

    from apps.leads.models import Lead

    lead = Lead.objects.get(id=thread.lead_id)
    assert lead.email == "engomondiii@gmail.com"
    assert lead.visitor_name == "Fidel Omondi"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_review_start_accumulates_company_from_an_earlier_turn(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="split-2")
    _visitor(thread, COVERING_TEXT)
    _visitor(thread, "Our company is GPSLAB")
    _prime_confirmed_customer(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )

    out = reveal_bridge.maybe_reveal_client_page(thread, "my email is engomondiii@gmail.com")
    thread.refresh_from_db()
    assert out["reason"] == "review_preparing"
    assert thread.lead_id is not None

    from apps.leads.models import Lead

    lead = Lead.objects.get(id=thread.lead_id)
    assert lead.company == "GPSLAB"


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
def test_no_review_start_without_email():
    thread = thread_svc.create_thread(visitor_session="gate-2")
    _visitor(thread, COVERING_TEXT)
    _prime_confirmed_customer(thread)
    out = reveal_bridge.maybe_reveal_client_page(thread, "our company is Acme")
    assert out["revealed"] is False
    assert out["reason"] == "no_email_yet"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_review_start_is_idempotent(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="idem-1")
    _visitor(thread, COVERING_TEXT)
    _prime_confirmed_customer(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )
    first = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")
    assert first["revealed"] is False
    assert first["reason"] == "review_preparing"
    thread.refresh_from_db()
    second = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")
    assert second["revealed"] is False
    assert second["reason"] in {"review_preparing", "already_has_lead"}


# ─────────────────────────────────────────────────────────────────────────────
# Secure readiness + AI directive
# ─────────────────────────────────────────────────────────────────────────────
@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, FRONTEND_WEB_URL="https://web.example")
def test_review_start_never_returns_a_browser_credential(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="tok-1")
    _visitor(thread, COVERING_TEXT)
    _prime_confirmed_customer(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )
    out = reveal_bridge.maybe_reveal_client_page(thread, "my email is a@b.com")

    assert out["reason"] == "review_preparing"
    assert out["token"] is None
    assert out["url"] is None
    assert thread.lead_id is not None


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
            "client_page_reveal": {"revealed": True, "access_code": "opaque-one-time-code"},
        },
    )
    prompt = agent._conversation_user_prompt(ctx, "ok", "INSTR")
    assert "MY REVIEW IS COMPLETE AND READY" in prompt
    assert "View My Review" in prompt
    assert "opaque-one-time-code" not in prompt
    assert "URL, token, code or internal identifier" in prompt
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
    assert "MY REVIEW IS COMPLETE AND READY" not in prompt


def test_client_page_reveal_fanout_has_access_code_without_capability_alias(monkeypatch):
    from apps.conversations.services import fan_out

    sent = []
    monkeypatch.setattr(fan_out, "_group_send", lambda group, event: sent.append((group, event)))
    fan_out.broadcast_reveal("thread.test", {
        "state": "CLIENT_PAGE",
        "surface": "client_page",
        "access_code": "opaque-code",
        "value_delivered": True,
    })
    event = sent[0][1]
    assert event["access_code"] == "opaque-code"
    assert event["capability_token"] is None


def test_account_invite_fanout_retains_legitimate_capability_token(monkeypatch):
    from apps.conversations.services import fan_out

    sent = []
    monkeypatch.setattr(fan_out, "_group_send", lambda group, event: sent.append((group, event)))
    fan_out.broadcast_reveal("lead.test", {
        "state": "INVITED",
        "surface": "account_invite",
        "capability_token": "invite-token",
    })
    event = sent[0][1]
    assert event["capability_token"] == "invite-token"
    assert event["access_code"] is None
