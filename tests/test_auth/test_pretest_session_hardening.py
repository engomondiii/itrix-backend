"""Focused regressions for the pre-MVP client-session hardening patch."""
from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.clients.services import password_reset as reset_svc
from apps.clients.tokens import build_tokens_for_client
from apps.clients.ws_ticket import resolve_client_ws_ticket
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _client_with_password(email: str = "session@example.com", password: str = "old-password-1234"):
    client = ClientFactory(email=email)
    client.credential.set_password(password)
    client.credential.save(update_fields=["password_hash", "updated_at"])
    return client


def test_password_change_revokes_access_refresh_and_ws_then_fresh_login_works(api_client, settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = _client_with_password()
    old = build_tokens_for_client(client)

    old_api = APIClient()
    old_api.credentials(HTTP_AUTHORIZATION=f"Bearer {old['access']}")
    assert old_api.get(reverse("clients:client-me")).status_code == 200
    assert api_client.post(
        reverse("clients:client-token-refresh"), {"refresh": old["refresh"]}, format="json"
    ).status_code == 200

    ticket_response = old_api.post(reverse("clients:portal-ws-ticket"), format="json")
    assert ticket_response.status_code == 200
    old_ticket = ticket_response.data["ticket"]
    assert resolve_client_ws_ticket(old_ticket).id == client.id

    reset_svc.change_password(client, "fresh-password-5678")
    client.refresh_from_db()
    assert client.session_version == 1
    assert client.password_changed_at is not None

    assert old_api.get(reverse("clients:client-me")).status_code == 401
    assert old_api.post(reverse("clients:portal-ws-ticket"), format="json").status_code == 401
    assert resolve_client_ws_ticket(old_ticket) is None
    assert api_client.post(
        reverse("clients:client-token-refresh"), {"refresh": old["refresh"]}, format="json"
    ).status_code == 401

    login = api_client.post(
        reverse("clients:client-login"),
        {"email": client.email, "password": "fresh-password-5678"},
        format="json",
    )
    assert login.status_code == 200
    fresh_access = login.data["access"]
    fresh_refresh = login.data["refresh"]

    fresh_api = APIClient()
    fresh_api.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh_access}")
    assert fresh_api.get(reverse("clients:client-me")).status_code == 200
    assert fresh_api.post(reverse("clients:portal-ws-ticket"), format="json").status_code == 200
    assert api_client.post(
        reverse("clients:client-token-refresh"), {"refresh": fresh_refresh}, format="json"
    ).status_code == 200


def test_password_reset_revokes_tokens_minted_before_reset(api_client, settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = _client_with_password(email="reset-session@example.com")
    old = build_tokens_for_client(client)

    from apps.clients.models_reset import PasswordResetToken, hash_token, new_token
    from django.utils import timezone

    token = new_token()
    PasswordResetToken.objects.create(
        client=client,
        token_hash=hash_token(token),
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    reset_svc.confirm_reset(token, "after-reset-password-789")

    old_api = APIClient()
    old_api.credentials(HTTP_AUTHORIZATION=f"Bearer {old['access']}")
    assert old_api.get(reverse("clients:client-me")).status_code == 401
    assert api_client.post(
        reverse("clients:client-token-refresh"), {"refresh": old["refresh"]}, format="json"
    ).status_code == 401


def test_team_token_cannot_mint_a_client_websocket_ticket(auth_client):
    response = auth_client.post(reverse("clients:portal-ws-ticket"), format="json")
    assert response.status_code in {401, 403}
