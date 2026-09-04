"""Identity, account, agreement, authorization and executed-contract state stay distinct."""
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.clients.permissions import ceiling_for_client
from apps.conversations.models_thread import Thread, ThreadContext, ThreadOwnerKind
from apps.journey.models import JourneyEvent
from apps.journey.services.advance import advance
from apps.knowledge_core.models import ContentAuthorization, KnowledgeDocument
from apps.ai_engine.services.disclosure_filter import filter_chunks
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _restricted_chunk(document, level="customer_contract", customer_scope=""):
    return {
        "document_id": str(document.id),
        "disclosure_level": level,
        "customer_scope": customer_scope,
        "metadata": {},
    }


def test_claimed_and_verified_identity_do_not_raise_client_baseline_ceiling():
    client = ClientFactory(
        claimed_identity={"name": "Claimed Person", "organization": "Claimed Org"},
        identity_verified_at=timezone.now(),
        organization_verified_at=timezone.now(),
        email_verified_at=timezone.now(),
    )
    assert ceiling_for_client(client) == "controlled_public"


def test_nda_and_executed_contract_still_require_explicit_content_authorization():
    client = ClientFactory(nda_signed=True, contract_state="executed")
    doc = KnowledgeDocument.objects.create(
        title="Customer contract note", namespace="tests", disclosure_level="customer_contract", is_current=True,
    )
    chunk = _restricted_chunk(doc, customer_scope=str(client.id))
    assert filter_chunks([chunk], context="customer_contract", customer_scope=str(client.id), contract_executed=True) == []

    ContentAuthorization.objects.create(
        document=doc,
        subject_kind=ContentAuthorization.SubjectKind.CLIENT,
        subject_id=str(client.id),
        reason="explicit test authorization",
    )
    assert filter_chunks(
        [chunk], context="customer_contract", customer_scope=str(client.id),
        authorized_document_ids={str(doc.id)}, contract_executed=True,
    ) == [chunk]


def test_executed_event_synchronizes_contract_facts_but_not_authorization():
    lead = LeadFactory(journey_state="INTEGRATION")
    client = ClientFactory(lead=lead, contract_state="")
    thread = Thread.objects.create(
        owner_kind=ThreadOwnerKind.CLIENT,
        client=client,
        lead=lead,
        context=ThreadContext.PORTAL,
        contract_stage="framework_discussion",
    )
    advance(lead, JourneyEvent.CONTRACT_EXECUTED.value, thread=thread)
    client.refresh_from_db(); thread.refresh_from_db()
    assert client.contract_state == "executed"
    assert thread.contract_stage == "executed"
    assert not ContentAuthorization.objects.filter(subject_kind="client", subject_id=str(client.id)).exists()
