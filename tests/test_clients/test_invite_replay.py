"""
SECURITY INVARIANT 1 — single-use means single-use (Backend v6.0 §Phase 1, §19.6).

The v4.0 build ran the invite RECOVERY path before the nonce burn. Every replay of a
single-use token found the existing Client and returned early, never reaching the burn —
so the token was single-use in name only. The same path could also SET A PASSWORD on an
existing account from an unauthenticated request.

These tests pin the corrected ordering: GATE -> NONCE BURN -> RECOVERY.

They are deliberately written against the OBSERVABLE behaviour (what a replay can
achieve) rather than against the implementation, so a future refactor that reintroduces
the bug fails here even if the code is arranged differently.
"""

from __future__ import annotations

import pytest

from apps.clients.models import Client
from apps.clients.services.invite import InviteError, claim_invite, mint_invite
from apps.journey.models import JourneyEvent
from apps.journey.services.advance import advance
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _invited_lead():
    lead = LeadFactory(journey_state="CLIENT_PAGE", tier=1)
    advance(lead, JourneyEvent.GATE_INVITE.value)  # -> INVITED
    return lead


def test_replay_is_refused_even_when_a_client_already_exists():
    """
    THE REGRESSION. A second claim with the same token must be refused.

    Before the fix this passed silently: the recovery path returned the existing client
    before the nonce was ever consumed.
    """
    lead = _invited_lead()
    token = mint_invite(lead)

    client, _ = claim_invite(token, email="first@example.com")
    assert client is not None

    with pytest.raises(InviteError):
        claim_invite(token, email="attacker@example.com")


def test_replay_cannot_set_a_password_on_an_existing_account():
    """
    An unauthenticated claim path must never set a credential on an existing account.

    This is the account-takeover half of the bug: anyone holding a copy of the invite
    link could previously supply a password and own the workspace.
    """
    lead = _invited_lead()
    token = mint_invite(lead)

    client, needs_password = claim_invite(token, email="owner@example.com")
    assert needs_password is True, "fixture assumption: no password set on first claim"

    with pytest.raises(InviteError):
        claim_invite(token, email="owner@example.com", password="attacker-chosen-pw")

    client.refresh_from_db()
    credential = getattr(client, "credential", None)
    assert not (credential and credential.has_password), (
        "the replayed claim must not have set a password"
    )


def test_replay_does_not_mutate_the_existing_client():
    """A refused replay must leave the account exactly as it was."""
    lead = _invited_lead()
    token = mint_invite(lead)
    client, _ = claim_invite(token, email="owner@example.com", full_name="Real Owner")

    original_email = client.email
    original_name = client.full_name

    with pytest.raises(InviteError):
        claim_invite(token, email="attacker@example.com", full_name="Attacker")

    client.refresh_from_db()
    assert client.email == original_email
    assert client.full_name == original_name


def test_only_one_client_is_ever_created_for_a_lead():
    lead = _invited_lead()
    token = mint_invite(lead)
    claim_invite(token, email="owner@example.com")
    with pytest.raises(InviteError):
        claim_invite(token, email="owner@example.com")
    assert Client.objects.filter(lead=lead).count() == 1


def test_client_page_token_is_not_burned_but_is_still_gated():
    """
    A client_page token is long-lived by design and must NOT be burned on claim.

    But the gate is still re-checked, so a long-lived token cannot create a workspace
    for a lead the journey never authorized. That re-check is what makes accepting this
    token type safe at all.
    """
    from apps.journey.services import capability_token as ct

    ungated = LeadFactory(
        journey_state="CLIENT_PAGE", tier=4, commercial_intent="", special_rights="None"
    )
    token = ct.mint(sub=str(ungated.id), typ=ct.TOKEN_CLIENT_PAGE, state="CLIENT_PAGE")

    with pytest.raises(InviteError):
        claim_invite(token, email="nope@example.com")
