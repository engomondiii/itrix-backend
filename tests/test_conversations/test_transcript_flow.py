"""End-to-end conversation regression for the explicit v2.2 Customer path.

The historical transcript used to auto-promote a sophisticated visitor, close the review band
on generic assent, ask for email, and place a reusable client-page token in the transcript.
The governed path is deliberately different: anonymous exploration may continue indefinitely;
a concrete workload-evaluation request creates a mode-change offer; explicit consent enters the
Customer band; STR-03 must be confirmed (or deliberately skipped) before an identity-dependent
action may produce a contact ask; and the email turn starts durable review generation without
putting a credential or /c/<token> URL in assistant prose.
"""
from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.models import Message, SenderKind
from apps.conversations.services import contact_ask, ingest, qualification, thread_state
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

LEGACY_TRANSCRIPT = (
    "Our training and inference cost is rising faster than the value it creates.",
    "Yes it will be useful",
    "pressure is primarily is on both, the scale is many",
    "Yes I would like to move forward",
)
COVERING_TEXT = (
    "Our training and inference workload runs on a GPU cluster with PyTorch and the cost "
    "is rising faster than the value it creates. We run 64 GPUs and it is urgent this quarter."
)
EMAIL_TURN = "My name is Fidel Omondi and my email is engomondiii@gmail.com"


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _agent_reply(thread, body="Understood — and one more question for you?"):
    return ingest.ingest_agent_message(
        thread.conversation, agent_key="concierge", body=body, thread=thread
    )


def _prime_customer(thread):
    thread.relationship_state = "customer"
    thread.mode_change_status = "consented"
    thread.mirror_status = "pending"
    thread.save(update_fields=["relationship_state", "mode_change_status", "mirror_status"])
    thread.refresh_from_db()


def _enter_customer_explicitly(thread):
    _visitor(thread, "Our inference workload is too expensive. Please evaluate the bottleneck.")
    thread.refresh_from_db()
    assert thread.relationship_state == "visitor"
    assert thread.mode_change_status == "offered"
    assert thread_state.current_state_key(thread) == "ARRIVED"

    _visitor(thread, "Yes, proceed.")
    thread.refresh_from_db()
    assert thread.relationship_state == "customer"
    assert thread.mode_change_status == "consented"
    assert thread_state.current_state_key(thread) == "IN_REVIEW"


def _reach_confirmed_action(thread):
    _enter_customer_explicitly(thread)
    _visitor(thread, COVERING_TEXT)
    thread.refresh_from_db()
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    assert thread.mirror_status == "pending"

    _visitor(thread, "Start a controlled evaluation")
    thread.refresh_from_db()
    assert thread.identity_needed_action == "formal_evaluation"
    assert getattr(thread, "_contact_ask", None) is None

    _visitor(thread, "This reflects my situation")
    thread.refresh_from_db()
    assert thread.mirror_status == "confirmed"
    decision = getattr(thread, "_contact_ask", None)
    assert decision and decision.get("ask") is True
    return decision


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_legacy_assent_transcript_remains_anonymous_without_an_evaluation_request():
    thread = thread_svc.create_thread(visitor_session="legacy-no-promotion")
    for body in LEGACY_TRANSCRIPT:
        _visitor(thread, body)
    thread.refresh_from_db()

    assert thread.relationship_state in {"visitor", "technical_evaluator"}
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert getattr(thread, "_contact_ask", None) is None
    assert thread.lead_id is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_explicit_customer_transition_then_str03_confirmation_enables_contact_ask():
    thread = thread_svc.create_thread(visitor_session="explicit-customer")
    decision = _reach_confirmed_action(thread)

    assert "email" in decision["text"].lower()
    assert "selected" in decision["text"].lower() or "action" in decision["text"].lower()


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=False)
def test_adaptive_question_flag_does_not_disable_the_explicit_customer_journey():
    thread = thread_svc.create_thread(visitor_session="flag-off")
    decision = _reach_confirmed_action(thread)

    assert decision["ask"] is True
    assert qualification.suggest_next(thread) == {}


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_email_after_confirmed_action_starts_review_without_url_or_token(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="review-pending")
    _reach_confirmed_action(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )

    _visitor(thread, EMAIL_TURN)
    thread.refresh_from_db()

    assert thread.lead_id is not None
    assert thread.lead.email == "engomondiii@gmail.com"
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    assert getattr(thread, "_client_page_reveal", None) is None
    assert getattr(thread, "_contact_ask", None) is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True, QUESTION_BUDGET_PER_STATE=4)
def test_customer_band_closes_on_delivered_reply_floor_when_emission_stalls():
    thread = thread_svc.create_thread(visitor_session="floor-1")
    _prime_customer(thread)
    vague = ("hello there", "it is complicated", "hard to say", "maybe", "not sure")
    for body in vague:
        _visitor(thread, body)
        thread.refresh_from_db()
        if thread_state.current_state_key(thread) == "DIAGNOSED":
            break
        _agent_reply(thread)
    thread.refresh_from_db()

    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    delivered = Message.objects.filter(thread=thread, sender_kind=SenderKind.AGENT).count()
    assert delivered >= 4


def test_questions_asked_floors_at_delivered_agent_replies():
    thread = thread_svc.create_thread(visitor_session="floor-2")
    _prime_customer(thread)
    _visitor(thread, "hello")
    for _ in range(3):
        _agent_reply(thread)
    assert qualification._questions_asked(thread) >= 3


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_turn_local_reveal_stash_is_cleared_on_a_later_non_reveal_turn():
    thread = thread_svc.create_thread(visitor_session="stash-1")
    thread._client_page_reveal = {"revealed": True, "access_code": "old-one-time-code"}

    _visitor(thread, "What does itriX do?")

    assert getattr(thread, "_client_page_reveal", None) is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_websocket_settle_never_embeds_review_access_data(monkeypatch):
    """Even a READY reveal in context stays out of assistant prose."""
    from apps.realtime.consumers import thread as thread_consumer

    thread = thread_svc.create_thread(visitor_session="ws-safe-handoff")
    _prime_customer(thread)
    thread._client_page_reveal = {
        "revealed": True,
        "access_code": "browser-bound-secret",
        "url": "https://web.example/c/legacy-secret",
    }
    ctx = thread_consumer._build_agent_context(thread, "thanks")

    monkeypatch.setattr(
        thread_consumer,
        "_govern",
        lambda text, _ctx: {"status": "auto_approved", "text": text},
    )
    settled = thread_consumer._settle(thread, "Your My Review is ready.", ctx)

    assert settled["under_review"] is False
    assert "browser-bound-secret" not in settled["body"]
    assert "legacy-secret" not in settled["body"]
    assert "/c/" not in settled["body"]
