"""
Client creator.

Turns an invited Lead into a ``Client`` (+ its ``ClientCredential``), links them 1:1,
mirrors the lead onto the client, and advances the journey INVITED → CLIENT (reveal
③). Idempotent: if the lead already has a client, that client is returned/updated
rather than duplicated.

Called by the invite-claim flow (``services.invite.claim_invite``). It never mints
tokens itself — the caller mints the client-JWT after creation so token lifetime is
controlled at the edge.
"""

from __future__ import annotations

import logging
import secrets

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client, ClientCredential

logger = logging.getLogger("itrix")


@transaction.atomic
def create_client_for_lead(
    lead,
    *,
    email: str | None = None,
    full_name: str = "",
    organization: str = "",
    role: str = "",
    password: str | None = None,
) -> tuple[Client, bool]:
    """
    Create (or fetch) the Client for ``lead``. Returns ``(client, created)``.

    Advances the journey INVITED → CLIENT via ``journey.advance`` on first creation
    (best-effort — a failed advance never orphans the client).
    """
    existing = Client.objects.filter(lead=lead).first()
    if existing:
        # Idempotent: if the client exists but has no password yet and one was
        # supplied, set it so the account becomes fully credentialed.
        if password:
            credential = getattr(existing, "credential", None)
            if credential is None:
                credential = ClientCredential(client=existing)
            if not credential.has_password:
                credential.set_password(password)
                credential.set_password_token = ""
                credential.set_password_expires_at = None
                credential.save()
        return existing, False

    client = Client.objects.create(
        lead=lead,
        email=(email or getattr(lead, "email", "") or "").strip(),
        full_name=full_name or getattr(lead, "visitor_name", "") or "",
        organization=organization or getattr(lead, "company", "") or "",
        role=role or getattr(lead, "role", "") or "",
    )

    credential = ClientCredential(client=client)
    if password:
        credential.set_password(password)
    else:
        # Mint a single-use set-password token so the client can choose a password.
        credential.set_password_token = secrets.token_urlsafe(32)
        credential.set_password_expires_at = timezone.now() + timezone.timedelta(hours=72)
    credential.save()

    # The 1:1 link is the Client.lead FK itself (reverse accessor: lead.client_account).
    # No extra stamping needed. Advance the journey INVITED → CLIENT (reveal ③).
    try:
        from apps.journey.services.advance import accept_invite

        accept_invite(lead, meta={"client_id": str(client.id)})
    except Exception:  # noqa: BLE001 - journey advance is best-effort here
        logger.exception("journey advance to CLIENT failed for lead %s", lead.id)

    # Phase 2: bootstrap the portal context — create the client's primary portal
    # conversation + participant so the portal has a thread the moment they log in.
    try:
        from apps.conversations.services.history import (
            get_or_create_portal_conversation,
            upsert_participant,
        )

        conv = get_or_create_portal_conversation(client)
        upsert_participant(conv, kind="client", client=client, display_name=client.display_name)
    except Exception:  # noqa: BLE001 - portal bootstrap is best-effort
        logger.exception("portal bootstrap failed for client %s", client.id)

    logger.info("Client %s created for lead %s", client.id, lead.id)
    return client, True


def authenticate_client(email: str, password: str) -> Client | None:
    """Return the active Client for these credentials, or None."""
    client = Client.objects.filter(email__iexact=(email or "").strip(), is_active=True).first()
    if client is None:
        return None
    credential = getattr(client, "credential", None)
    if credential is None or not credential.check_password(password):
        return None
    client.last_login_at = timezone.now()
    client.save(update_fields=["last_login_at", "updated_at"])
    return client
