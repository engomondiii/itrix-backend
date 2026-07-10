"""
Client first-time / reset password set.

Consumes the single-use ``set_password_token`` minted by ``client_creator`` when a
Client is created without a password (e.g. an email-only invite claim). Verifying the
token sets the password, clears the token, and returns the Client so the caller can
mint a fresh client-JWT — landing the visitor directly in their workspace.

This is the safety net for the "no password chosen at claim time" path. In the v4.1
flow the visitor normally chooses a password during the claim itself, so this endpoint
is only exercised for legacy / email-only invites.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client, ClientCredential

logger = logging.getLogger("itrix")


class SetPasswordError(Exception):
    """Raised when a set-password token is invalid, expired, or already used."""


@transaction.atomic
def set_password_with_token(token: str, password: str) -> Client:
    """Set a client's password from a single-use token. Returns the Client."""
    token = (token or "").strip()
    if not token or not password:
        raise SetPasswordError("Missing token or password.")

    credential = (
        ClientCredential.objects.select_for_update()
        .filter(set_password_token=token)
        .first()
    )
    if credential is None:
        raise SetPasswordError("Invalid or already-used link.")

    expires = credential.set_password_expires_at
    if expires is not None and expires < timezone.now():
        raise SetPasswordError("This link has expired.")

    credential.set_password(password)
    credential.set_password_token = ""
    credential.set_password_expires_at = None
    credential.save(
        update_fields=[
            "password_hash",
            "set_password_token",
            "set_password_expires_at",
            "updated_at",
        ]
    )

    client = credential.client
    if not client.is_active:
        raise SetPasswordError("This account is not active.")

    client.last_login_at = timezone.now()
    client.save(update_fields=["last_login_at", "updated_at"])
    logger.info("Client %s set password via token", client.id)
    return client
