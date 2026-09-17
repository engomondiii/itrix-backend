"""Thread claim continuity across open and invite account creation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.clients.models import Client
from apps.clients.services.invite import mint_invite
from apps.clients.services.invite_versioned import claim_invite_with_version_integrity
from apps.clients.services.registration import register_client
from apps.conversations.models import ThreadOwnerKind
from apps.conversations.services import ingest, threads as thread_svc
from apps.conversations.services.claim import claim_threads
from apps.legal.constants import ASSENT_REQUIRED_SLUGS
from apps.legal.models import AssentRecord
from apps.legal.services import instruments as instruments_svc
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _assent_versions():
    return instruments_svc.current_versions(ASSENT_REQUIRED_SLUGS)


def _anonymous_history(session: str):
    thread = thread_svc.create_thread(visitor_session=session)
    ingest.ingest_inbound(
        thread.conversation,
        sender_kind="visitor",
        body="Keep this exact anonymous turn.",
        thread=thread,
    )
    return thread


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
    lead = LeadFactory()
    client = ClientFactory(lead=lead)
    thread = thread_svc.create_thread(visitor_session="sess-1")
    assert thread.retention_expires_at is not None

    claim_threads(visitor_session="sess-1", client=client, lead=lead)
    thread.refresh_from_db()
    assert thread.retention_expires_at is None


def test_claim_never_touches_another_session():
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


def test_open_registration_claims_exact_anonymous_thread_and_turns():
    thread = _anonymous_history("open-history")
    outcome = register_client(
        email="history-open@example.com",
        password="a-long-enough-password",
        full_name="History Owner",
        organization="Example",
        assent_versions=_assent_versions(),
        visitor_session="open-history",
    )

    thread.refresh_from_db()
    assert thread.client_id == outcome.client.id
    assert thread.owner_kind == ThreadOwnerKind.CLIENT
    assert list(thread.messages.values_list("body", flat=True)) == ["Keep this exact anonymous turn."]
    assert thread_svc.list_for_client(outcome.client).filter(id=thread.id).exists()


def test_open_registration_rolls_back_if_thread_claim_fails_and_retry_succeeds():
    thread = _anonymous_history("open-fail")

    with patch("apps.conversations.services.claim.claim_threads", side_effect=RuntimeError("claim failed")):
        with pytest.raises(RuntimeError, match="claim failed"):
            register_client(
                email="history-fail@example.com",
                password="a-long-enough-password",
                full_name="History Owner",
                organization="Example",
                assent_versions=_assent_versions(),
                visitor_session="open-fail",
            )

    assert not Client.objects.filter(email="history-fail@example.com").exists()
    assert not AssentRecord.objects.filter(client_email_at_assent="history-fail@example.com").exists()
    thread.refresh_from_db()
    assert thread.client_id is None
    assert thread.owner_kind == ThreadOwnerKind.SESSION
    assert list(thread.messages.values_list("body", flat=True)) == ["Keep this exact anonymous turn."]

    retry = register_client(
        email="history-fail@example.com",
        password="a-long-enough-password",
        full_name="History Owner",
        organization="Example",
        assent_versions=_assent_versions(),
        visitor_session="open-fail",
    )
    thread.refresh_from_db()
    assert thread.client_id == retry.client.id


def test_invite_claim_rolls_back_nonce_client_and_assent_when_thread_claim_fails():
    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)
    thread = _anonymous_history("invite-fail")

    with patch("apps.conversations.services.claim.claim_threads", side_effect=RuntimeError("claim failed")):
        with pytest.raises(RuntimeError, match="claim failed"):
            claim_invite_with_version_integrity(
                token,
                email="history-invite@example.com",
                password="a-long-enough-password",
                full_name="Invite Owner",
                organization="Example",
                assent_versions=_assent_versions(),
                visitor_session="invite-fail",
            )

    assert not Client.objects.filter(lead=lead).exists()
    assert not AssentRecord.objects.filter(client_email_at_assent="history-invite@example.com").exists()
    thread.refresh_from_db()
    assert thread.client_id is None
    assert thread.owner_kind == ThreadOwnerKind.SESSION

    # The same single-use token must still work: its nonce burn was part of the rolled-back
    # outer transaction rather than being stranded ahead of history continuity.
    client, _requires_password = claim_invite_with_version_integrity(
        token,
        email="history-invite@example.com",
        password="a-long-enough-password",
        full_name="Invite Owner",
        organization="Example",
        assent_versions=_assent_versions(),
        visitor_session="invite-fail",
    )
    thread.refresh_from_db()
    assert thread.client_id == client.id
    assert list(thread.messages.values_list("body", flat=True)) == ["Keep this exact anonymous turn."]
