"""
EMAIL CONFIRMATION (Architecture v2.9 R66, Backend v7.2 §15.10).

The most important assertion here is the NEGATIVE one: confirmation gates three things and
nothing else. An unconfirmed account can sign in, hold a conversation and receive answers —
gating the composer on a mailbox round-trip would reintroduce exactly the wait open
registration exists to remove.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models_verification import EmailVerificationToken, hash_token
from apps.clients.services import verification as verification_svc
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _mint(client):
    token = verification_svc.mint(client, client.email)
    assert EmailVerificationToken.objects.filter(token_hash=hash_token(token)).exists()
    return token


def test_a_token_works_once(api_client):
    client = ClientFactory(email="confirm@example.com")
    token = _mint(client)
    url = reverse("clients:auth-verify-confirm")

    assert api_client.post(url, {"token": token}, format="json").status_code == 200
    assert api_client.post(url, {"token": token}, format="json").status_code == 410

    client.refresh_from_db()
    assert client.email_verified_at is not None


def test_requesting_a_new_link_invalidates_the_previous_one(api_client):
    client = ClientFactory(email="confirm@example.com")
    first = _mint(client)
    second = _mint(client)
    url = reverse("clients:auth-verify-confirm")
    assert api_client.post(url, {"token": first}, format="json").status_code == 410
    assert api_client.post(url, {"token": second}, format="json").status_code == 200


def test_an_expired_link_gets_the_same_error_as_an_unknown_one(api_client):
    client = ClientFactory(email="confirm@example.com")
    token = _mint(client)
    EmailVerificationToken.objects.filter(client=client).update(
        expires_at=timezone.now() - timezone.timedelta(hours=1)
    )
    url = reverse("clients:auth-verify-confirm")
    expired = api_client.post(url, {"token": token}, format="json")
    unknown = api_client.post(url, {"token": "not-a-real-token"}, format="json")
    assert expired.status_code == unknown.status_code == 410
    assert expired.content == unknown.content


def test_the_token_carries_the_address_it_was_issued_for(api_client):
    """
    If the account's address changes between the send and the click, the OLD link must not
    confirm the NEW address — otherwise somebody could point an account at another person's
    mailbox and confirm it with a link issued for their own.
    """
    client = ClientFactory(email="original@example.com")
    _mint(client)
    record = EmailVerificationToken.objects.get(client=client)
    assert record.email == "original@example.com"


def test_resend_answers_identically_for_every_case(api_client):
    confirmed = ClientFactory(email="done@example.com", email_verified_at=timezone.now())
    pending = ClientFactory(email="pending@example.com")
    url = reverse("clients:auth-verify-resend")

    a = api_client.post(url, {"email": confirmed.email}, format="json")
    b = api_client.post(url, {"email": pending.email}, format="json")
    c = api_client.post(url, {"email": "nobody@example.com"}, format="json")
    assert a.status_code == b.status_code == c.status_code == 202
    assert a.content == b.content == c.content


def test_confirmation_gates_non_transactional_email_and_nothing_more(settings):
    """R66 item 1, enforced at the single choke-point for outbound mail."""
    settings.REQUIRE_EMAIL_VERIFICATION = True
    client = ClientFactory(email="pending@example.com")

    from apps.emails.models import EmailLog
    from apps.emails.services.email_sender import send_email

    blocked = send_email(
        kind=EmailLog.Kind.FOLLOW_UP, to_email=client.email, subject="A follow-up", body="hello"
    )
    assert blocked.status == EmailLog.Status.FAILED
    assert "unconfirmed" in blocked.error.lower()

    # The three transactional kinds must still get through, because confirming the address
    # is what they are for.
    for kind in (EmailLog.Kind.EMAIL_VERIFICATION, EmailLog.Kind.PASSWORD_RESET, EmailLog.Kind.ADDRESS_IN_USE):
        allowed = send_email(kind=kind, to_email=client.email, subject="s", body="b")
        assert allowed.status != EmailLog.Status.FAILED

    client.email_verified_at = timezone.now()
    client.save(update_fields=["email_verified_at"])
    now_allowed = send_email(
        kind=EmailLog.Kind.FOLLOW_UP, to_email=client.email, subject="A follow-up", body="hello"
    )
    assert now_allowed.status != EmailLog.Status.FAILED


def test_a_non_account_address_is_never_gated(settings):
    """
    The gate is about CONFIRMED ACCOUNTS, not about every address we have ever seen. A lead
    who has not opened a workspace still gets their follow-up.
    """
    settings.REQUIRE_EMAIL_VERIFICATION = True

    from apps.emails.models import EmailLog
    from apps.emails.services.email_sender import send_email

    log = send_email(
        kind=EmailLog.Kind.FOLLOW_UP, to_email="just.a.lead@example.com", subject="s", body="b"
    )
    assert log.status != EmailLog.Status.FAILED


def test_an_unconfirmed_account_may_still_sign_in(api_client, settings):
    """The negative assertion. Confirmation is not a login gate."""
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory(email="pending@example.com")
    client.credential.set_password("a-long-enough-password")
    client.credential.save()

    res = api_client.post(
        reverse("clients:client-login"),
        {"email": client.email, "password": "a-long-enough-password"},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["client"]["emailVerified"] is False


def test_anonymous_resend_with_email_really_mints_and_sends(api_client):
    from unittest.mock import patch

    client = ClientFactory(email="resend-now@example.com")
    url = reverse("clients:auth-verify-resend")

    with patch("apps.clients.services.verification.send") as send:
        response = api_client.post(url, {"email": client.email}, format="json")

    assert response.status_code == 202
    record = EmailVerificationToken.objects.get(client=client, consumed_at__isnull=True)
    assert record.email == client.email
    send.assert_called_once()


def test_authenticated_resend_can_omit_email(api_client):
    from unittest.mock import patch
    from apps.clients.tokens import build_tokens_for_client

    client = ClientFactory(email="resend-auth@example.com")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(client)['access']}")

    with patch("apps.clients.services.verification.send") as send:
        response = api_client.post(reverse("clients:auth-verify-resend"), {}, format="json")

    assert response.status_code == 202
    assert EmailVerificationToken.objects.filter(client=client, consumed_at__isnull=True).exists()
    send.assert_called_once()
