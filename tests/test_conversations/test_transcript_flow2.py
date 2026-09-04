"""Regression for bare assent, identity capture, and combined contact extraction.

Bare assent is only meaningful in context.  It must not turn an anonymous Visitor into a
Customer or close a review band.  When the user has explicitly entered Customer assessment,
confirmed STR-03, and selected an identity-dependent action, the governed contact ask may run;
a supplied email starts review preparation, while organization remains optional enrichment.
"""
from __future__ import annotations

import pytest
from django.test import override_settings

from apps.conversations.models import SenderKind
from apps.conversations.services import contact_ask, ingest, reveal_bridge, thread_state
from apps.conversations.services import threads as thread_svc

pytestmark = pytest.mark.django_db

COVERING_TEXT = (
    "Our training and inference workload runs on a GPU cluster with PyTorch and the cost "
    "is rising faster than the value it creates. We run 64 GPUs and it is urgent this quarter."
)
EMAIL_TURN = "engomondiii@gmail.com"


def _visitor(thread, body):
    return ingest.ingest_inbound(
        thread.conversation, sender_kind=SenderKind.VISITOR, body=body, thread=thread
    )


def _prime_actionable_customer(thread, *, diagnosed=True):
    thread.relationship_state = "customer"
    thread.mode_change_status = "consented"
    thread.mirror_status = "confirmed"
    thread.identity_needed_action = "formal_evaluation"
    thread.selected_action = "start_controlled_evaluation"
    thread.save(
        update_fields=[
            "relationship_state",
            "mode_change_status",
            "mirror_status",
            "identity_needed_action",
            "selected_action",
        ]
    )
    if diagnosed:
        thread_state._mirror_onto_thread(thread, "DIAGNOSED")
    thread.refresh_from_db()


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_yes_please_without_a_mode_change_offer_does_not_promote_or_ask():
    thread = thread_svc.create_thread(visitor_session="t2-accept")
    _visitor(thread, "Our training and inference cost is rising faster than the value it creates.")
    _visitor(thread, "Yes please")
    thread.refresh_from_db()

    assert thread.relationship_state == "visitor"
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert getattr(thread, "_contact_ask", None) is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_informational_assent_does_not_start_customer_assessment():
    thread = thread_svc.create_thread(visitor_session="t2-info")
    _visitor(thread, "What does ALPHA Compute do?")
    _visitor(thread, "Yes it would help")
    thread.refresh_from_db()

    assert thread.relationship_state in {"visitor", "technical_evaluator"}
    assert thread_state.current_state_key(thread) == "ARRIVED"


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_bare_assent_on_the_first_turn_does_nothing_commercial():
    thread = thread_svc.create_thread(visitor_session="t2-first")
    _visitor(thread, "yes")
    thread.refresh_from_db()

    assert thread.relationship_state == "visitor"
    assert thread_state.current_state_key(thread) == "ARRIVED"
    assert thread.lead_id is None


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_confirmed_identity_action_asks_for_email_with_anonymous_opt_out():
    thread = thread_svc.create_thread(visitor_session="t2-ask")
    _prime_actionable_customer(thread)

    decision = contact_ask.evaluate(thread, "")

    assert decision["ask"] is True
    assert "work email" in decision["text"].lower()
    assert "continue" in decision["text"].lower()
    assert "anonym" in decision["text"].lower()


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_organisation_alone_does_not_satisfy_identity_requirement():
    thread = thread_svc.create_thread(visitor_session="t2-orgonly")
    _prime_actionable_customer(thread)
    first = contact_ask.evaluate(thread, "")
    contact_ask.record_asked(thread, first)
    _visitor(thread, "GPSLAB")
    thread.refresh_from_db()

    assert thread.lead_id is None
    decision = getattr(thread, "_contact_ask", None)
    assert decision and decision.get("ask") is True
    assert decision.get("asks_made") == 1
    assert "work email" in decision["text"].lower()


def test_org_comma_email_answer_is_captured():
    c = reveal_bridge.extract_contact_from_text("GPSLAB, engomondiii@gmail.com")
    assert c["email"] == "engomondiii@gmail.com"
    assert c["company"] == "GPSLAB"


@pytest.mark.parametrize("text", ["Sure, engomondiii@gmail.com", "Thanks, x@y.com", "engomondiii@gmail.com"])
def test_courtesy_openers_are_not_captured_as_an_organisation(text):
    assert reveal_bridge.extract_contact_from_text(text)["company"] == ""


@override_settings(ENABLE_ADAPTIVE_QUESTIONS=True)
def test_combined_answer_starts_review_with_organisation_without_exposing_access(monkeypatch):
    thread = thread_svc.create_thread(visitor_session="t2-combined")
    _prime_actionable_customer(thread)
    monkeypatch.setattr(
        "apps.review.services.qualification_processor.kick_off_result_page",
        lambda lead, finalize_conversation=False: None,
    )

    _visitor(thread, "GPSLAB, engomondiii@gmail.com")
    thread.refresh_from_db()

    assert thread.lead_id is not None
    assert thread.lead.email == "engomondiii@gmail.com"
    assert thread.lead.company == "GPSLAB"
    assert thread_state.current_state_key(thread) == "DIAGNOSED"
    assert getattr(thread, "_client_page_reveal", None) is None
