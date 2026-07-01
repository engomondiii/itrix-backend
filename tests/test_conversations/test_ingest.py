"""Conversation ingest: inbound + agent + team turns; thread bookkeeping."""

from __future__ import annotations

import pytest

from apps.conversations.models import GovernanceStatus, SenderKind
from apps.conversations.services import ingest
from apps.conversations.services.history import (
    deliverable_messages,
    get_or_create_review_conversation,
    unread_count,
)
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_get_or_create_review_conversation_is_idempotent():
    lead = LeadFactory()
    c1 = get_or_create_review_conversation(review_session_id="sess-1", lead=lead)
    c2 = get_or_create_review_conversation(review_session_id="sess-1", lead=lead)
    assert c1.id == c2.id


def test_ingest_inbound_is_deliverable():
    lead = LeadFactory()
    conv = get_or_create_review_conversation(review_session_id="s", lead=lead)
    msg = ingest.ingest_inbound(conv, sender_kind=SenderKind.VISITOR, body="hi")
    assert msg.is_deliverable
    assert conv.last_message_at is not None
    assert deliverable_messages(conv).count() == 1


def test_ingest_agent_message_pending_is_not_deliverable():
    lead = LeadFactory()
    conv = get_or_create_review_conversation(review_session_id="s", lead=lead)
    msg = ingest.ingest_agent_message(
        conv, agent_key="concierge", body="held draft", governance_status=GovernanceStatus.PENDING
    )
    assert not msg.is_deliverable
    # pending messages are excluded from the client-facing deliverable list
    assert deliverable_messages(conv).count() == 0


def test_unread_count_excludes_own_messages():
    from tests.factories.client_factory import ClientFactory
    from apps.conversations.services.history import get_or_create_portal_conversation

    client = ClientFactory()
    conv = get_or_create_portal_conversation(client)
    ingest.ingest_inbound(conv, sender_kind=SenderKind.CLIENT, body="mine", client=client)
    ingest.ingest_agent_message(conv, agent_key="concierge", body="reply")
    # Only the agent reply counts as unread for the client.
    assert unread_count(conv, client=client) == 1
