"""The portal exchanges its httpOnly HTTP session for a narrow WebSocket ticket."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.clients.ws_ticket import resolve_client_ws_ticket
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def test_portal_ws_ticket_requires_client_auth():
    response = APIClient().post("/api/v1/portal/ws-ticket/", format="json")
    assert response.status_code in {401, 403}


def test_portal_ws_ticket_resolves_only_to_authenticated_client():
    client = ClientFactory()
    access = build_tokens_for_client(client)["access"]
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = api.post("/api/v1/portal/ws-ticket/", format="json")
    assert response.status_code == 200
    assert response.data["expiresIn"] > 0
    resolved = resolve_client_ws_ticket(response.data["ticket"])
    assert resolved is not None
    assert resolved.id == client.id
