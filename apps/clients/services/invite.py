"""
Account-invite service.

Reveal ② mints an ``account_invite`` capability token (single-use, TTL =
ACCOUNT_INVITE_TTL_HOURS) for a lead that passed the invite gate. Reveal ③ consumes
it: ``claim_invite`` verifies the token, asserts the journey permits an invite, creates
the Client, and returns it so the view can mint a client-JWT.

Single-use enforcement: the token's nonce is consumed atomically by recording it in a
``ConsumedInvite`` row keyed by nonce. Re-claiming a consumed token fails.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.clients.models import Client
from apps.clients.services.client_creator import create_client_for_lead
from apps.journey.models import JourneyState
from apps.journey.services import capability_token as ct
from apps.journey.services.gate import account_invite_allowed

logger = logging.getLogger("itrix")


class InviteError(Exception):
    """Raised when an invite cannot be minted or claimed."""


def mint_invite(lead) -> str:
    """Mint a single-use account_invite token for a gate-passing lead."""
    if not account_invite_allowed(lead):
        raise InviteError("Lead has not passed the account-invite gate.")
    ttl = int(getattr(settings, "ACCOUNT_INVITE_TTL_HOURS", 72)) * 3600
    return ct.mint(
        sub=str(lead.id),
        typ=ct.TOKEN_ACCOUNT_INVITE,
        state=lead.journey_state or JourneyState.INVITED,
        ttl_seconds=ttl,
        single_use=True,
    )


@transaction.atomic
def claim_invite(
    token: str,
    *,
    email: str | None = None,
    password: str | None = None,
    full_name: str = "",
    organization: str = "",
    role: str = "",
) -> tuple[Client, bool]:
    """
    Consume an account_invite token → create the Client (reveal ③).

    Returns ``(client, requires_password_set)``. Raises ``InviteError`` on an invalid,
    expired, wrong-typed, or already-consumed token, or if the lead may not be invited.
    """
    try:
        payload = ct.verify(token, expected_typ=ct.TOKEN_ACCOUNT_INVITE)
    except ct.CapabilityTokenError as exc:
        raise InviteError(f"Invalid invite: {exc}") from exc

    from apps.leads.models import Lead

    lead = Lead.objects.select_for_update().filter(id=payload.sub).first()
    if lead is None:
        raise InviteError("Unknown invite subject.")

    # The journey must still permit an invite (gate re-checked at claim time).
    if not account_invite_allowed(lead):
        raise InviteError("This lead is no longer eligible for a workspace invite.")

    # Consume the single-use nonce atomically.
    if payload.single_use:
        from apps.clients.models_consumed import ConsumedInvite

        try:
            ConsumedInvite.objects.create(nonce=payload.nonce, lead_id=str(lead.id))
        except IntegrityError as exc:
            raise InviteError("This invite has already been used.") from exc

    client, created = create_client_for_lead(
        lead,
        email=email,
        password=password,
        full_name=full_name,
        organization=organization,
        role=role,
    )

    credential = getattr(client, "credential", None)
    requires_password_set = not (credential and credential.has_password)
    return client, requires_password_set
