"""
PASSWORD RESET (Backend v7.2 §15.3).

── FOUR PROPERTIES, AND THREE OF THEM ARE ABOUT WHAT WE DO NOT SAY ─────────
  1. the request is answered identically whether or not the address has a workspace,
     and in comparable time
  2. the token is single-use, short-lived, and BURNED BEFORE the password is written,
     in one transaction
  3. a password change invalidates every other session
  4. rate limiting is server-side and surfaces as a stated wait

── WHY THE ORDERING IN (2) IS WRITTEN DOWN RATHER THAN ASSUMED ─────────────
`claim_invite`'s recovery branch used to run before the nonce burn, so a single-use invite
token could be replayed indefinitely and `test_single_use_enforced` failed. This flow is
the same shape with the same temptation — a helpful early return — so the order is stated,
tested, and commented at the line where it matters.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connection, transaction
from django.utils import timezone

from apps.clients.models_reset import PasswordResetToken, hash_token, new_token

logger = logging.getLogger("itrix")


class ResetError(Exception):
    """One error for expired, consumed and unknown alike."""


def ttl_minutes() -> int:
    return int(getattr(settings, "RESET_TOKEN_TTL_MINUTES", 60))


def request_reset(email: str, *, ip: str | None = None) -> None:
    """
    Send a reset link, or do exactly nothing — and take a comparable amount of time either
    way.

    Returns None in both cases. Not a bool: a caller that could branch on the outcome would
    be one edit away from reporting it, and the whole point is that the answer is
    indistinguishable.
    """
    from apps.clients.models import Client

    address = (email or "").strip()
    client = Client.objects.filter(email__iexact=address, is_active=True).first() if address else None

    if client is None:
        # A dummy hash so the two branches do not differ measurably. Timing is a weaker
        # oracle than a different response body, but it is the same oracle, and closing it
        # costs one call.
        make_password(new_token())
        logger.info("clients.reset_requested_unknown_address")
        return

    with transaction.atomic():
        PasswordResetToken.objects.filter(
            client=client, consumed_at__isnull=True, invalidated_at__isnull=True
        ).update(invalidated_at=timezone.now())

        token = new_token()
        PasswordResetToken.objects.create(
            client=client,
            token_hash=hash_token(token),
            expires_at=timezone.now() + timezone.timedelta(minutes=ttl_minutes()),
            requested_ip=ip or None,
        )

    try:
        from apps.emails.models import EmailLog
        from apps.emails.services.password_reset_builder import build_password_reset_email

        mail = build_password_reset_email(client, token=token)
        # `send_email()` records provider failures in EmailLog instead of raising, because
        # every outbound attempt must leave an audit row. Inspect that result here so a
        # reset-specific delivery failure is visible in Railway logs without exposing the
        # address or token. The public endpoint still returns the same 202 for every
        # address, preserving the anti-enumeration contract.
        if mail.status == EmailLog.Status.FAILED:
            logger.error(
                "clients.password_reset_delivery_failed client=%s email_log=%s",
                client.id,
                mail.id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("password reset email failed for client %s", client.id)


def confirm_reset(token: str, new_password: str):
    """
    Burn the token, then write the password, then invalidate other sessions — one
    transaction, in that order.
    """
    from apps.clients.models import ClientCredential
    from apps.clients.services.session_invalidation import invalidate_other_sessions

    digest = hash_token(token)
    with transaction.atomic():
        qs = PasswordResetToken.objects.filter(token_hash=digest)
        if connection.features.has_select_for_update:
            qs = qs.select_for_update()
        record = qs.select_related("client").first()
        if record is None or not record.is_usable:
            raise ResetError("That link is no longer usable.")

        # THE BURN, FIRST. Everything below this line runs only once for a given token,
        # even under two concurrent requests.
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at", "updated_at"])

        client = record.client
        credential = getattr(client, "credential", None)
        if credential is None:
            credential = ClientCredential(client=client)
        credential.set_password(new_password)
        credential.set_password_token = ""
        credential.set_password_expires_at = None
        credential.save()

        invalidate_other_sessions(client)
        logger.info("clients.password_reset client=%s", client.id)
        return client


def change_password(client, new_password: str):
    """The authenticated change. Same session-invalidation contract as a reset."""
    from apps.clients.models import ClientCredential
    from apps.clients.services.session_invalidation import invalidate_other_sessions

    with transaction.atomic():
        credential = getattr(client, "credential", None)
        if credential is None:
            credential = ClientCredential(client=client)
        credential.set_password(new_password)
        credential.save()
        invalidate_other_sessions(client)
    return client
