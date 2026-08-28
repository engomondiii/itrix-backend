"""Invite recovery keeps invite and set-password capabilities separate and one-use."""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.services.invite import mint_invite
from apps.journey.models import JourneyEvent
from apps.journey.services.advance import advance
from tests.factories.client_factory import ClientFactory
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _invite_for_passwordless_existing_client():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1)
    advance(lead, JourneyEvent.GATE_INVITE)
    invite = mint_invite(lead)
    client = ClientFactory(lead=lead, credential__password=None)
    assert not client.credential.has_password
    return invite, client


def test_existing_passwordless_invitee_gets_dedicated_set_password_capability(settings):
    settings.ENABLE_CLIENT_PORTAL = True
    invite, client = _invite_for_passwordless_existing_client()
    api = APIClient()

    claim = api.post(f"/api/v1/accounts/invite/{invite}/claim/", {}, format="json")
    assert claim.status_code == 201
    assert claim.data["requiresPasswordSet"] is True
    set_password_token = claim.data["setPasswordToken"]
    assert set_password_token
    assert set_password_token != invite

    # The invitation credential cannot be repurposed as a password credential.
    wrong_purpose = api.post(
        "/api/v1/client/auth/password/set/",
        {"token": invite, "password": "Valid-password-12345"},
        format="json",
    )
    assert wrong_purpose.status_code == 400

    too_short = api.post(
        "/api/v1/client/auth/password/set/",
        {"token": set_password_token, "password": "short-pass"},
        format="json",
    )
    assert too_short.status_code == 400

    completed = api.post(
        "/api/v1/client/auth/password/set/",
        {"token": set_password_token, "password": "Valid-password-12345"},
        format="json",
    )
    assert completed.status_code == 200
    client.refresh_from_db()
    client.credential.refresh_from_db()
    assert client.credential.check_password("Valid-password-12345")

    # Password capability and invitation are both one-use.
    assert api.post(
        "/api/v1/client/auth/password/set/",
        {"token": set_password_token, "password": "Another-valid-password-678"},
        format="json",
    ).status_code == 400
    assert api.post(f"/api/v1/accounts/invite/{invite}/claim/", {}, format="json").status_code == 404
