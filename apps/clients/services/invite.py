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
    visitor_session: str = "",
) -> tuple[Client, bool]:
    """
    Consume a capability token → create the Client (reveal ③).

    Accepts EITHER an ``account_invite`` token (the dedicated single-use invite) OR the
    ``client_page`` token the visitor already holds in their URL. Both are signed
    capability tokens bound to the same lead via ``sub``; accepting the client_page
    token lets the front-end claim with the token it already has, without a separate
    invite-token round-trip. Security is preserved because the journey gate
    (``account_invite_allowed``) is re-checked here regardless of token type — a
    client_page token can only create a workspace once the journey authorizes it.

    Returns ``(client, requires_password_set)``. Raises ``InviteError`` on an invalid,
    expired, wrong-typed, or already-consumed token, or if the lead may not be invited.
    """
    # Accept either token type. Verify signature+expiry once we know which it is.
    payload = None
    last_error: Exception | None = None
    for expected in (ct.TOKEN_ACCOUNT_INVITE, ct.TOKEN_CLIENT_PAGE):
        try:
            payload = ct.verify(token, expected_typ=expected)
            break
        except ct.CapabilityTokenError as exc:
            last_error = exc
    if payload is None:
        raise InviteError(f"Invalid invite: {last_error}")

    from apps.leads.models import Lead

    lead = Lead.objects.select_for_update().filter(id=payload.sub).first()
    if lead is None:
        raise InviteError("Unknown invite subject.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECURITY INVARIANT 1 — ORDER IS THE SECURITY PROPERTY
    # ─────────────────────────────────────────────────────────────────────────
    # Backend v6.0 §Phase 1: reorder to GATE -> NONCE BURN -> RECOVERY.
    #
    # The v4.0 build ran the recovery path FIRST, which meant a single-use invite token
    # could be replayed indefinitely: every replay found the existing Client and
    # returned early, before reaching the nonce burn. The token was single-use in name
    # only.
    #
    # It also let that unauthenticated recovery path SET A PASSWORD on an existing
    # account. Anyone holding a copy of the invite link could take over the workspace.
    #
    # The rule, restated: a single-use token MUST be consumed BEFORE any code path that
    # can return a subject, and NO unauthenticated claim path may set a credential on an
    # existing account.
    # ─────────────────────────────────────────────────────────────────────────

    # 1) GATE. The journey must permit an invite. Re-checked at claim time regardless of
    #    which token type was presented — this is what makes accepting the long-lived
    #    client_page token safe.
    existing = Client.objects.filter(lead=lead).select_related("credential").first()
    if existing is None and not account_invite_allowed(lead):
        raise InviteError("This lead is no longer eligible for a workspace invite.")

    # 2) BURN. Consume the single-use nonce atomically, BEFORE anything can return a
    #    subject — including the recovery path below. A replayed token dies here.
    if payload.single_use and payload.typ == ct.TOKEN_ACCOUNT_INVITE:
        from apps.clients.models_consumed import ConsumedInvite

        try:
            ConsumedInvite.objects.create(nonce=payload.nonce, lead_id=str(lead.id))
        except IntegrityError as exc:
            raise InviteError("This invite has already been used.") from exc

    # 3) RECOVERY. Only now may we return an existing workspace. A refresh or a
    #    double-submit still logs the visitor in rather than dead-ending them at
    #    "we'll be in touch" — but a REPLAY has already been stopped at step 2.
    if existing is not None:
        _apply_recovery_details(
            existing,
            email=email,
            full_name=full_name,
            organization=organization,
            role=role,
        )
        credential = getattr(existing, "credential", None)
        requires_password_set = not (credential and credential.has_password)
        _claim_session_threads(lead, existing, visitor_session)
        return existing, requires_password_set

    client, created = create_client_for_lead(
        lead,
        email=email,
        password=password,
        full_name=full_name,
        organization=organization,
        role=role,
    )

    # Migrate the visitor's anonymous threads INSIDE this transaction, after the burn
    # (Backend v6.0 §2.2). Every turn, artifact and attachment follows them in.
    _claim_session_threads(lead, client, visitor_session)

    credential = getattr(client, "credential", None)
    requires_password_set = not (credential and credential.has_password)
    return client, requires_password_set


def _apply_recovery_details(
    client,
    *,
    email: str | None,
    full_name: str,
    organization: str,
    role: str,
) -> None:
    """
    Fill in missing profile details on an already-existing client during recovery.

    SECURITY: this function DOES NOT SET A PASSWORD, and it must never be given the
    ability to. Setting a credential here would mean an unauthenticated caller holding a
    copy of an invite link could take over an existing workspace.

    A client who needs a password gets one through the authenticated set-password flow
    (``apps.clients.services.set_password``), which proves control of the mailbox first.

    Only ever fills fields that are currently EMPTY — never clobbers existing data.
    """
    changed: list[str] = []
    if email and not client.email:
        client.email = email.strip()
        changed.append("email")
    if full_name and not client.full_name:
        client.full_name = full_name
        changed.append("full_name")
    if organization and not client.organization:
        client.organization = organization
        changed.append("organization")
    if role and not client.role:
        client.role = role
        changed.append("role")
    if changed:
        changed.append("updated_at")
        client.save(update_fields=changed)


def _claim_session_threads(lead, client, visitor_session: str) -> None:
    """
    Migrate the visitor's anonymous threads to the new Client.

    Runs inside the caller's transaction, AFTER the nonce burn. Best-effort by design:
    a visitor who never spoke has no threads, and that is normal rather than an error.
    """
    if not visitor_session:
        return
    try:
        from apps.conversations.services.claim import claim_threads

        claim_threads(visitor_session=visitor_session, client=client, lead=lead)
    except Exception:  # noqa: BLE001 - never fail a workspace creation on thread claim
        logger.exception("thread claim failed for client %s", getattr(client, "id", "?"))
