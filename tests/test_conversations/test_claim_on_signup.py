"""
Thread claim on signup (Backend v6.0 §2.2).

When an anonymous visitor creates a workspace, the threads they built must follow them.
Otherwise they lose the conversation they came to have.
"""

from __future__ import annotations

import pytest

from apps.conversations.models import Thread, ThreadOwnerKind
from apps.conversations.services import threads as thread_svc
from apps.conversations.services.claim import claim_threads
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_claim_migrates_every_thread_from_the_session():
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    a = thread_svc.create_thread(visitor_session="sess-1")
    b = thread_svc.create_thread(visitor_session="sess-1")

    claimed = claim_threads(visitor_session="sess-1", client=client, lead=lead)
    assert {t.id for t in claimed} == {a.id, b.id}

    a.refresh_from_db()
    assert a.client_id == client.id
    assert a.owner_kind == ThreadOwnerKind.CLIENT
    assert a.claimed_at is not None


def test_claim_clears_the_anonymous_retention_window():
    """
    Leaving it set would DELETE a paying customer's history on the next sweep. This is
    the line that prevents that.
    """
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    thread = thread_svc.create_thread(visitor_session="sess-1")
    assert thread.retention_expires_at is not None

    claim_threads(visitor_session="sess-1", client=client, lead=lead)
    thread.refresh_from_db()
    assert thread.retention_expires_at is None


def test_claim_never_touches_another_session():
    """A PRIVACY BOUNDARY, not an optimisation. Sessions are never merged."""
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    mine = thread_svc.create_thread(visitor_session="sess-mine")
    theirs = thread_svc.create_thread(visitor_session="sess-theirs")

    claim_threads(visitor_session="sess-mine", client=client, lead=lead)

    theirs.refresh_from_db()
    assert theirs.client_id is None
    assert theirs.owner_kind == ThreadOwnerKind.SESSION
    mine.refresh_from_db()
    assert mine.client_id == client.id


def test_claiming_with_no_threads_is_not_an_error():
    """A visitor who never spoke has no threads. Normal, not exceptional."""
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    assert claim_threads(visitor_session="sess-empty", client=client, lead=lead) == []


def test_claim_carries_the_conversation_across():
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    thread = thread_svc.create_thread(visitor_session="sess-1")
    conversation_id = thread.conversation_id

    claim_threads(visitor_session="sess-1", client=client, lead=lead)

    from apps.conversations.models import Conversation

    conversation = Conversation.objects.get(id=conversation_id)
    assert conversation.client_id == client.id
