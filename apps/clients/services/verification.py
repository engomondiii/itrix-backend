"""
EMAIL CONFIRMATION (Backend v7.2 §15.10, Architecture v2.9 R66).

── WHAT IT GATES, AND WHAT IT MUST NOT ─────────────────────────────────────
Three things:

  1. any NON-TRANSACTIONAL email  — enforced in `apps.emails.services.email_sender`,
                                    which is the single choke-point for outbound mail
  2. putting an NDA in place      — `nda_allowed()`, enforced where an NDA is sent
  3. being named on a commercial document

And NOTHING else. Not signing in, not posting a turn, not receiving an answer, not
keeping a thread. Gating the composer on a mailbox round-trip would reintroduce exactly
the wait open registration exists to remove, for somebody who has already told us what
they need.

── BURN BEFORE THE WRITE, IN ONE TRANSACTION ───────────────────────────────
The third flow in this codebase with the same shape and the same temptation. `claim_invite`
once ran its recovery branch BEFORE the nonce burn, so a single-use invite token could be
replayed and `test_single_use_enforced` failed. The reset flow was written to avoid it. This
is named here so a helpful early-return does not reintroduce it a third time.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.clients.models_verification import EmailVerificationToken, hash_token, new_token

logger = logging.getLogger("itrix")

# Mail that must reach an address BEFORE it is confirmed, because confirming it is what
# these messages are for. Everything else waits.
TRANSACTIONAL_EMAIL_KINDS = frozenset({"email_verification", "password_reset", "address_in_use"})


class VerificationError(Exception):
    """One error for expired, consumed and unknown alike."""


def required() -> bool:
    return bool(getattr(settings, "REQUIRE_EMAIL_VERIFICATION", True))


def ttl_hours() -> int:
    return int(getattr(settings, "VERIFICATION_TOKEN_TTL_HOURS", 48))


def is_verified(client) -> bool:
    return getattr(client, "email_verified_at", None) is not None


def mint(client, email: str = "", *, ip: str | None = None) -> str:
    """
    Mint a token, invalidating any earlier one. Returns the PLAINTEXT, which is never stored.

    Called inside the transaction that creates the account; the email goes out on commit.
    A token with no mail is fixed by a resend. A mail carrying a token that was rolled back
    is a support conversation about a link that never worked.
    """
    address = (email or getattr(client, "email", "") or "").strip()
    EmailVerificationToken.objects.filter(
        client=client, consumed_at__isnull=True, invalidated_at__isnull=True
    ).update(invalidated_at=timezone.now())

    token = new_token()
    EmailVerificationToken.objects.create(
        client=client,
        email=address,
        token_hash=hash_token(token),
        expires_at=timezone.now() + timezone.timedelta(hours=ttl_hours()),
        requested_ip=ip or None,
    )
    return token


def send(client, token: str) -> None:
    """Deliver the link. Best-effort: a failed send is recoverable by a resend."""
    try:
        from apps.emails.services.verification_email_builder import build_verification_email

        build_verification_email(client, token=token)
    except Exception:  # noqa: BLE001 - never fail an account creation on a mail failure
        logger.exception("verification email failed for client %s", getattr(client, "id", "?"))


def confirm(token: str) -> "object":
    """
    Consume a token and mark the address confirmed.

    ORDER IS THE SECURITY PROPERTY: the token is marked consumed BEFORE the flag is
    written, in one transaction, so two simultaneous attempts produce exactly one
    confirmation.
    """
    digest = hash_token(token)
    with transaction.atomic():
        qs = EmailVerificationToken.objects.filter(token_hash=digest)
        # SQLite has no row locks; its whole-database write lock provides the same
        # serialisation for this transaction. Postgres gets the row lock. Asking for one
        # where the backend has none raises, so the capability is checked rather than
        # assumed.
        if connection.features.has_select_for_update:
            qs = qs.select_for_update()
        record = qs.first()
        if record is None or not record.is_usable:
            # One error for expired, consumed and unknown. The caller cannot tell them
            # apart, and neither can anyone probing tokens.
            raise VerificationError("That link is no longer usable.")

        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at", "updated_at"])

        client = record.client
        if client.email_verified_at is None:
            client.email_verified_at = timezone.now()
            client.save(update_fields=["email_verified_at", "updated_at"])
        logger.info("clients.email_verified client=%s", client.id)
        return client


def resend(email: str, *, ip: str | None = None) -> None:
    """
    Send another link, or do nothing at all — the caller cannot tell which.

    Enumeration safety lives in the VIEW's response, but it is worth noting here too: this
    function returns None in every case, so a caller cannot accidentally branch on an
    outcome and reintroduce the oracle the response is careful to avoid.
    """
    from apps.clients.models import Client

    address = (email or "").strip()
    if not address:
        return
    client = Client.objects.filter(email__iexact=address, is_active=True).first()
    if client is None or is_verified(client):
        return
    with transaction.atomic():
        token = mint(client, client.email, ip=ip)
    send(client, token)


def nda_allowed(client) -> tuple[bool, str]:
    """
    Whether an NDA may be put in place for this client (R66 item 2).

    Fail-OPEN when there is no client at all: a team-created NDA for a lead with no
    account is a normal operational case and has nothing to verify. Fail-CLOSED only for a
    real account with an unconfirmed address, and only while the requirement is on.
    """
    if client is None or not required():
        return True, ""
    if is_verified(client):
        return True, ""
    return False, (
        "This workspace's email address has not been confirmed yet, so an NDA cannot be "
        "sent to it. Ask the customer to confirm the address, or resend the confirmation "
        "link from their account."
    )


def may_send(kind: str, to_email: str) -> tuple[bool, str]:
    """
    Whether this outbound mail may go to this address (R66 item 1).

    Called by `email_sender.send_email`, which is the only place outbound mail is created.
    Putting the check anywhere else would mean every future builder has to remember it.
    """
    if not required():
        return True, ""
    if kind in TRANSACTIONAL_EMAIL_KINDS:
        return True, ""

    from apps.clients.models import Client

    address = (to_email or "").strip()
    if not address:
        return True, ""
    client = Client.objects.filter(email__iexact=address, is_active=True).first()
    if client is None or is_verified(client):
        # Not an account holder at all — a lead, a visitor, an internal recipient. This
        # gate is about CONFIRMED ACCOUNTS, not about every address we have ever seen.
        return True, ""
    return False, "Recipient address is an unconfirmed itriX workspace (Architecture v2.9 R66)."
