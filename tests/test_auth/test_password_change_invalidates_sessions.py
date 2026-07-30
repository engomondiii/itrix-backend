"""
A PASSWORD CHANGE ENDS EVERY OTHER SESSION (Backend v7.2 §15.3 property 3).

── HOW YOU INVALIDATE A STATELESS JWT ──────────────────────────────────────
You cannot revoke one. `password_changed_at` is stamped, and the client plane refuses a
token minted before it. The guarantee therefore lives in TWO places, and either one alone is
silently useless — so this asserts the stamp, and `test_the_stamp_is_actually_checked`
asserts the other half.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.clients.services import password_reset as reset_svc
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def test_the_authenticated_change_requires_the_current_password(api_client, settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory(email="member@example.com")
    client.credential.set_password("the-current-password")
    client.credential.save()

    from apps.clients.tokens import build_tokens_for_client

    tokens = build_tokens_for_client(client)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    wrong = api_client.post(
        reverse("clients:client-password-change"),
        {"currentPassword": "not-it", "newPassword": "a-brand-new-password"},
        format="json",
    )
    assert wrong.status_code == 401

    right = api_client.post(
        reverse("clients:client-password-change"),
        {"currentPassword": "the-current-password", "newPassword": "a-brand-new-password"},
        format="json",
    )
    assert right.status_code == 200
    assert right.data["otherSessionsSignedOut"] is True


def test_changing_a_password_stamps_the_invalidation(api_client):
    client = ClientFactory(email="member@example.com")
    assert client.password_changed_at is None
    reset_svc.change_password(client, "a-brand-new-password")
    client.refresh_from_db()
    assert client.password_changed_at is not None
