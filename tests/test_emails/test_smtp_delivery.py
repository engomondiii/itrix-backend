"""
SMTP delivery through the single choke-point (`email_sender.send_email`).

── WHAT THESE TESTS ARE FOR ────────────────────────────────────────────────
The sign-up confirmation link is sent by `verification.send()` -> the verification
builder -> `send_email`. Before this change `send_email` could only talk to Resend, so a
deployment with SMTP credentials logged every message as `stubbed` and no link ever
arrived. These assert the SMTP path end to end using Django's locmem backend, which is a
real mail backend and therefore exercises the same code a real send does.

They also pin the two properties that are easy to lose in a refactor: a failure is never
recorded as `sent`, and "delivery is on but nothing is configured" is a FAILED row with
the fix in the message rather than a stubbed row that looks intentional.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings

from apps.emails.models import EmailLog
from apps.emails.services.email_sender import send_email

pytestmark = pytest.mark.django_db

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND=LOCMEM,
    EMAIL_FROM="gpslab@iwl.kr",
    EMAIL_FROM_NAME="iTrix Assessment Team",
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_smtp_send_delivers_and_records_sent():
    mail.outbox.clear()
    log = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="Confirm your email address",
        body="Please confirm this is your address: https://example.test/verify-email?token=abc",
    )

    assert log.status == EmailLog.Status.SENT
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["visitor@gmail.com"]
    assert message.subject == "Confirm your email address"
    assert "verify-email?token=abc" in message.body
    # The display name travels with the address, and the address is the authenticated
    # mailbox — Gmail rejects a From it does not own.
    assert message.from_email == "iTrix Assessment Team <gpslab@iwl.kr>"


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND=LOCMEM,
    EMAIL_FROM="gpslab@iwl.kr",
    EMAIL_FROM_NAME="",
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_from_header_is_the_bare_address_when_no_display_name():
    mail.outbox.clear()
    send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="s",
        body="b",
    )
    assert mail.outbox[0].from_email == "gpslab@iwl.kr"


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND=LOCMEM,
    EMAIL_FROM="gpslab@iwl.kr",
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_a_gmail_address_is_not_treated_differently_from_a_company_address():
    """
    Nothing anywhere refuses a personal mailbox.

    There never was a domain restriction — the backend serializer is a plain EmailField —
    but the sign-up copy said "work email", which read as one. This pins the behaviour so
    a future "helpful" domain check has to break a test to get in.
    """
    mail.outbox.clear()
    for address in ("someone@gmail.com", "someone@samsung.com", "someone@yahoo.co.kr"):
        log = send_email(
            kind=EmailLog.Kind.EMAIL_VERIFICATION,
            to_email=address,
            subject="Confirm your email address",
            body="link",
        )
        assert log.status == EmailLog.Status.SENT, address
    assert len(mail.outbox) == 3


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="none",
    EMAIL_BACKEND=LOCMEM,
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_delivery_on_with_no_provider_is_a_failure_not_a_stub():
    mail.outbox.clear()
    log = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="s",
        body="b",
    )
    assert log.status == EmailLog.Status.FAILED
    assert "EMAIL_HOST_USER" in log.error
    assert mail.outbox == []


@override_settings(
    ENABLE_EMAIL_DELIVERY=False,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND=LOCMEM,
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_the_flag_still_wins_over_a_working_provider():
    mail.outbox.clear()
    log = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="s",
        body="b",
    )
    assert log.status == EmailLog.Status.STUBBED
    assert mail.outbox == []


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND="tests.test_emails.test_smtp_delivery.ExplodingBackend",
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_a_provider_failure_is_recorded_as_failed_never_as_sent():
    log = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="s",
        body="b",
    )
    assert log.status == EmailLog.Status.FAILED
    assert "SMTPAuthenticationError" in log.error or "nope" in log.error


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND="tests.test_emails.test_smtp_delivery.SilentBackend",
    REQUIRE_EMAIL_VERIFICATION=False,
)
def test_a_backend_that_sends_nothing_is_a_failure():
    """
    `send()` returning 0 means accepted-and-not-delivered.

    Recording that as `sent` would be worse than the error it hides: "sent" is a claim we
    would quote back to somebody who never received the message.
    """
    log = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION,
        to_email="visitor@gmail.com",
        subject="s",
        body="b",
    )
    assert log.status == EmailLog.Status.FAILED
    assert "0 sent" in log.error


@override_settings(
    ENABLE_EMAIL_DELIVERY=True,
    EMAIL_PROVIDER="smtp",
    EMAIL_BACKEND=LOCMEM,
    REQUIRE_EMAIL_VERIFICATION=True,
)
def test_the_confirmation_gate_still_binds_on_the_smtp_path():
    """
    R66 item 1 is enforced at the choke-point, so adding a provider must not bypass it.

    A non-transactional kind addressed to an unconfirmed workspace is refused, and the
    refusal is still a FAILED row — a refusal that left no trace is indistinguishable from
    a message nobody tried to send.
    """
    from apps.clients.services.client_creator import create_client_for_lead
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory(email="held@gmail.com")
    client, _ = create_client_for_lead(
        lead, email="held@gmail.com", password="a-long-enough-password", full_name="Held"
    )
    assert client.email_verified_at is None

    mail.outbox.clear()
    log = send_email(kind=EmailLog.Kind.FOLLOW_UP, to_email="held@gmail.com", subject="s", body="b")
    assert log.status == EmailLog.Status.FAILED
    assert "unconfirmed" in log.error.lower()
    assert mail.outbox == []

    # ...and a transactional kind to the same address goes through.
    log2 = send_email(
        kind=EmailLog.Kind.EMAIL_VERIFICATION, to_email="held@gmail.com", subject="s", body="b"
    )
    assert log2.status == EmailLog.Status.SENT
    assert len(mail.outbox) == 1


# ── Test doubles. Module-level so EMAIL_BACKEND can name them by import path. ──
from django.core.mail.backends.base import BaseEmailBackend  # noqa: E402


class ExplodingBackend(BaseEmailBackend):
    def send_messages(self, email_messages):  # noqa: ARG002
        raise RuntimeError("nope")


class SilentBackend(BaseEmailBackend):
    def send_messages(self, email_messages):  # noqa: ARG002
        return 0
