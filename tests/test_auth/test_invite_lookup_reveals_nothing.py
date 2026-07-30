"""
THE INVITE LOOKUP (Backend v7.2 §15.4).

An unauthenticated endpoint reachable by anyone with a guessable string. EVERYTHING it
returns is a disclosure, so it returns two fields — and one answer for three causes.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.clients.services.invite import mint_invite
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _lookup(api_client, code):
    return api_client.get(reverse("clients:auth-invite-lookup"), {"code": code})


def test_a_usable_code_returns_only_usable_and_a_url(api_client):
    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)
    res = _lookup(api_client, token)
    assert res.status_code == 200
    assert res.data["usable"] is True
    assert "create-account" in res.data["redeemUrl"]
    # Two fields, and nothing else. Not the organisation, not the persona, not the email.
    assert set(res.data.keys()) == {"usable", "redeemUrl"}


def test_it_reveals_no_lead_detail_for_any_code(api_client):
    lead = LeadFactory(tier=1, journey_state="INVITED", company="Acme Corp", email="ceo@acme.example")
    token = mint_invite(lead)
    body = _lookup(api_client, token).content.decode()
    assert "Acme" not in body
    assert "acme.example" not in body
    assert str(lead.id) not in body


def test_three_failure_causes_produce_one_answer(api_client):
    """Unknown, already claimed, and not-yet-eligible. One body, one status."""
    unknown = _lookup(api_client, "not-a-real-token")

    claimed_lead = LeadFactory(tier=1, journey_state="INVITED")
    claimed_token = mint_invite(claimed_lead)
    ClientFactory(lead=claimed_lead)
    claimed = _lookup(api_client, claimed_token)

    ineligible_lead = LeadFactory(tier=4, commercial_intent="Just exploring", journey_state="CLIENT_PAGE")
    ineligible = _lookup(api_client, "also-not-real")

    assert unknown.status_code == claimed.status_code == ineligible.status_code == 200
    assert unknown.content == claimed.content == ineligible.content
    assert unknown.data == {"usable": False}


def test_a_lookup_does_not_consume_the_code(api_client):
    """
    A lookup that burned the nonce would mean CHECKING a code destroyed it. The burn belongs
    at claim time, before anything can return a subject.
    """
    from apps.clients.models_consumed import ConsumedInvite

    lead = LeadFactory(tier=1, journey_state="INVITED")
    token = mint_invite(lead)
    _lookup(api_client, token)
    _lookup(api_client, token)
    assert not ConsumedInvite.objects.exists()
    assert _lookup(api_client, token).data["usable"] is True
