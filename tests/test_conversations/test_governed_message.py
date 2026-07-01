"""Review-chat service: persists turns + Concierge reply, governance-aware."""

from __future__ import annotations

import pytest

from apps.review.services.review_chat import handle_review_chat_turn
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_review_chat_persists_and_replies(settings):
    settings.ENABLE_AGENTS = False  # deterministic Concierge fallback
    lead = LeadFactory(product_route="alpha_compute", tier=2)
    result = handle_review_chat_turn(review_session_id="sess-x", lead=lead, body="Can you help?")
    assert result.reply  # fallback holding message
    assert result.under_review is False
    assert result.governance_status == "auto_approved"

    from apps.conversations.models import Conversation

    conv = Conversation.objects.get(id=result.conversation_id)
    # visitor turn + agent turn
    assert conv.messages.count() == 2


def test_review_chat_creates_single_thread_per_session(settings):
    settings.ENABLE_AGENTS = False
    lead = LeadFactory()
    r1 = handle_review_chat_turn(review_session_id="sess-y", lead=lead, body="one")
    r2 = handle_review_chat_turn(review_session_id="sess-y", lead=lead, body="two")
    assert r1.conversation_id == r2.conversation_id
