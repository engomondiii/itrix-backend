"""Invite flow: mint → claim creates client, single-use, gate enforced."""

from __future__ import annotations

import pytest

from apps.clients.services.invite import InviteError, claim_invite, mint_invite
from apps.journey.models import JourneyEvent, JourneyState
from apps.journey.services.advance import advance
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _invited_lead():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1)
    advance(lead, JourneyEvent.GATE_INVITE)  # → INVITED
    return lead


def test_mint_requires_gate():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=4, commercial_intent="", special_rights="None")
    with pytest.raises(InviteError):
        mint_invite(lead)


def test_claim_creates_client_and_advances():
    """UPDATED FOR v6.0: accepting an invite now lands on NDA_REVIEW (was CLIENT)."""
    lead = _invited_lead()
    token = mint_invite(lead)
    client, needs_pw = claim_invite(token, email="x@y.com")
    lead.refresh_from_db()
    assert client.email == "x@y.com"
    assert lead.journey_state == JourneyState.NDA_REVIEW
    assert needs_pw is True


def test_single_use_enforced():
    lead = _invited_lead()
    token = mint_invite(lead)
    claim_invite(token, email="x@y.com")
    with pytest.raises(InviteError):
        claim_invite(token, email="x@y.com")


def test_bad_token_rejected():
    with pytest.raises(InviteError):
        claim_invite("not-a-real-token", email="x@y.com")
