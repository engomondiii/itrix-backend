"""
PASSWORD RESET (Backend v7.2 §15.3).

`test_the_token_works_once` is the direct analogue of `test_single_use_enforced`, which the
invite path FAILED: `claim_invite`'s recovery branch ran before the nonce burn, so a
single-use token could be replayed indefinitely. This flow is the same shape with the same
temptation, which is why the ordering is asserted rather than assumed.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models_reset import PasswordResetToken, hash_token
from apps.clients.services import password_reset as reset_svc
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _request_and_capture(client):
    reset_svc.request_reset(client.email)
    record = PasswordResetToken.objects.filter(client=client).order_by("-created_at").first()
    assert record is not None
    from apps.emails.models import EmailLog

    mail = EmailLog.objects.filter(kind=EmailLog.Kind.PASSWORD_RESET).order_by("-created_at").first()
    assert mail is not None
    token = mail.body.split("token=")[1].split()[0].strip()
    assert hash_token(token) == record.token_hash
    return token


def test_the_request_is_answered_identically_for_a_known_and_unknown_address(api_client):
    known = ClientFactory(email="known@example.com")
    url = reverse("clients:auth-reset-request")
    a = api_client.post(url, {"email": known.email}, format="json")
    b = api_client.post(url, {"email": "nobody@example.com"}, format="json")
    assert a.status_code == b.status_code == 202
    assert a.content == b.content


def test_the_token_works_once(api_client):
    client = ClientFactory(email="reset@example.com")
    token = _request_and_capture(client)
    url = reverse("clients:auth-reset-confirm")

    first = api_client.post(url, {"token": token, "password": "a-brand-new-password"}, format="json")
    assert first.status_code == 200

    second = api_client.post(url, {"token": token, "password": "another-new-password"}, format="json")
    assert second.status_code == 410

    client.refresh_from_db()
    assert client.credential.check_password("a-brand-new-password")


def test_requesting_a_new_link_invalidates_the_previous_one(api_client):
    client = ClientFactory(email="reset@example.com")
    first_token = _request_and_capture(client)
    second_token = _request_and_capture(client)
    url = reverse("clients:auth-reset-confirm")

    stale = api_client.post(url, {"token": first_token, "password": "x" * 14}, format="json")
    assert stale.status_code == 410
    fresh = api_client.post(url, {"token": second_token, "password": "y" * 14}, format="json")
    assert fresh.status_code == 200


def test_an_expired_token_is_refused_with_the_same_error(api_client):
    client = ClientFactory(email="reset@example.com")
    token = _request_and_capture(client)
    PasswordResetToken.objects.filter(client=client).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )
    res = api_client.post(
        reverse("clients:auth-reset-confirm"),
        {"token": token, "password": "z" * 14},
        format="json",
    )
    assert res.status_code == 410


def test_a_reset_invalidates_other_sessions_and_says_so(api_client):
    client = ClientFactory(email="reset@example.com")
    assert client.password_changed_at is None
    token = _request_and_capture(client)
    res = api_client.post(
        reverse("clients:auth-reset-confirm"),
        {"token": token, "password": "q" * 14},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["otherSessionsSignedOut"] is True
    client.refresh_from_db()
    assert client.password_changed_at is not None


def test_the_token_is_never_stored_in_plaintext(api_client):
    client = ClientFactory(email="reset@example.com")
    token = _request_and_capture(client)
    for record in PasswordResetToken.objects.all():
        assert token not in record.token_hash
        assert len(record.token_hash) == 64


def test_password_reset_email_opts_into_bounded_delivery_retry(settings, monkeypatch):
    settings.PASSWORD_RESET_EMAIL_ATTEMPTS = 2
    client = ClientFactory(email="retry-reset@example.com")
    seen = {}

    def fake_send_email(**kwargs):
        seen.update(kwargs)
        from apps.emails.models import EmailLog

        return EmailLog.objects.create(
            kind=kwargs["kind"],
            to_email=kwargs["to_email"],
            subject=kwargs["subject"],
            body=kwargs["body"],
            status=EmailLog.Status.STUBBED,
        )

    monkeypatch.setattr("apps.emails.services.password_reset_builder.send_email", fake_send_email)
    reset_svc.request_reset(client.email)
    assert seen["delivery_attempts"] == 2


def test_password_reset_records_a_reset_specific_log_when_delivery_fails(caplog, monkeypatch):
    from apps.emails.models import EmailLog

    client = ClientFactory(email="failed-reset@example.com")

    def fake_builder(target, *, token):  # noqa: ARG001
        return EmailLog.objects.create(
            kind=EmailLog.Kind.PASSWORD_RESET,
            to_email=target.email,
            subject="Reset your itriX password",
            body="not delivered",
            status=EmailLog.Status.FAILED,
            error="provider unavailable",
        )

    monkeypatch.setattr(
        "apps.emails.services.password_reset_builder.build_password_reset_email",
        fake_builder,
    )
    with caplog.at_level("ERROR", logger="itrix"):
        reset_svc.request_reset(client.email)

    assert "clients.password_reset_delivery_failed" in caplog.text
    assert client.email not in caplog.text
