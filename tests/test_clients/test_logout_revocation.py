from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def test_logout_revokes_retained_refresh_and_new_login_generation_works(settings):
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory()
    issued = build_tokens_for_client(client)

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued['access']}")
    logout = api.post("/api/v1/client/auth/logout/", {}, format="json")
    assert logout.status_code == 200
    assert logout.data["revoked"] is True

    # A copied refresh credential from before logout must be dead immediately.
    anonymous = APIClient()
    rejected = anonymous.post(
        "/api/v1/client/auth/token/refresh/",
        {"refresh": issued["refresh"]},
        format="json",
    )
    assert rejected.status_code == 401

    # A subsequent authenticated session uses the advanced generation normally.
    client.refresh_from_db()
    fresh = build_tokens_for_client(client)
    accepted = anonymous.post(
        "/api/v1/client/auth/token/refresh/",
        {"refresh": fresh["refresh"]},
        format="json",
    )
    assert accepted.status_code == 200
    assert accepted.data.get("access")


def test_logout_does_not_claim_revocation_when_database_write_fails(settings, monkeypatch):
    settings.ENABLE_CLIENT_PORTAL = True
    client = ClientFactory()
    issued = build_tokens_for_client(client)

    def fail(_client):
        raise RuntimeError("database detail must stay private")

    monkeypatch.setattr("apps.clients.views_logout.revoke_current_session", fail)

    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued['access']}")
    response = api.post(
        "/api/v1/client/auth/logout/",
        {},
        format="json",
        HTTP_X_REQUEST_ID="req-client-logout-failure",
    )
    assert response.status_code == 503
    assert response.data["code"] == "SESSION_REVOCATION_UNAVAILABLE"
    assert response.data["requestId"] == "req-client-logout-failure"
    assert "database detail" not in str(response.data)

    # Since the durable write failed, the old refresh remains valid. This proves the 503
    # is materially different from a successful revocation response.
    refresh = APIClient().post(
        "/api/v1/client/auth/token/refresh/",
        {"refresh": issued["refresh"]},
        format="json",
    )
    assert refresh.status_code == 200
