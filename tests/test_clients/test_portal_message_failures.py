from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.clients.tokens import build_tokens_for_client
from apps.conversations.services.history import get_or_create_portal_conversation
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def _authed(row) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {build_tokens_for_client(row)['access']}")
    return api


@override_settings(MAX_MESSAGE_CHARS=3)
def test_known_message_size_error_is_safe_413_with_code_and_request_id():
    row = ClientFactory()
    conv = get_or_create_portal_conversation(row)
    response = _authed(row).post(
        f"/api/v1/portal/conversations/{conv.id}/messages/",
        {"body": "long"},
        format="json",
        HTTP_X_REQUEST_ID="req-portal-too-long",
    )
    assert response.status_code == 413
    assert response.data["code"] == "MESSAGE_TOO_LONG"
    assert response.data["requestId"] == "req-portal-too-long"
    assert "longer than we can accept" in response.data["detail"]


def test_unknown_portal_ingest_error_is_not_413_and_never_leaks_raw_exception(monkeypatch, caplog):
    row = ClientFactory()
    conv = get_or_create_portal_conversation(row)

    def explode(*args, **kwargs):
        raise RuntimeError("database hostname and secret detail")

    monkeypatch.setattr("apps.conversations.services.ingest.ingest_inbound", explode)
    response = _authed(row).post(
        f"/api/v1/portal/conversations/{conv.id}/messages/",
        {"body": "hello"},
        format="json",
        HTTP_X_REQUEST_ID="req-portal-db-failure",
    )

    assert response.status_code == 503
    assert response.status_code != 413
    assert response.data["code"] == "PORTAL_MESSAGE_UNAVAILABLE"
    assert response.data["requestId"] == "req-portal-db-failure"
    assert "database hostname" not in str(response.data)
    assert "req-portal-db-failure" in caplog.text
