"""Client creator: creates a client for a lead, idempotent, advances journey."""

from __future__ import annotations

import pytest

from apps.clients.models import Client
from apps.clients.services.client_creator import authenticate_client, create_client_for_lead
from apps.journey.models import JourneyState
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_create_client_links_lead_and_advances_journey():
    lead = LeadFactory(journey_state="INVITED", email="buyer@acme.io")
    client, created = create_client_for_lead(lead, email="buyer@acme.io")
    lead.refresh_from_db()
    assert created is True
    assert client.lead_id == lead.id
    # v6.0: CLIENT was renamed to NDA_REVIEW (state 6).
    assert lead.journey_state == JourneyState.NDA_REVIEW
    assert lead.client_account == client  # reverse 1:1 accessor


def test_create_client_is_idempotent():
    lead = LeadFactory(journey_state="INVITED")
    c1, created1 = create_client_for_lead(lead)
    c2, created2 = create_client_for_lead(lead)
    assert created1 is True and created2 is False
    assert c1.id == c2.id
    assert Client.objects.filter(lead=lead).count() == 1


def test_authenticate_client_with_password():
    lead = LeadFactory(journey_state="INVITED")
    client, _ = create_client_for_lead(lead, email="a@b.com", password="hunter2-strong")
    assert authenticate_client("a@b.com", "hunter2-strong") == client
    assert authenticate_client("a@b.com", "wrong") is None


def test_client_without_password_cannot_auth():
    lead = LeadFactory(journey_state="INVITED")
    client, _ = create_client_for_lead(lead, email="np@b.com")  # no password
    assert authenticate_client("np@b.com", "anything") is None
