"""
RATE LIMITING IS A STATED WAIT, NOT A SILENT FAILURE (Backend v7.2 §15.3 property 4).

`tests/conftest.py` switches `AUTH_RATE_LIMIT_ENABLED` off for the whole suite so that a test
posting twice does not trip a real limit. This file turns it back on, because a control
nobody exercises is a control nobody knows works.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

pytestmark = pytest.mark.django_db

ASSENT = [{"slug": "terms", "version": "1.2", "effective": "2026-07-30"}]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def test_the_limit_returns_429_with_a_retry_after(api_client, settings):
    settings.AUTH_RATE_LIMIT_ENABLED = True
    settings.AUTH_RATE_LIMIT_PER_ADDRESS = "2/hour"
    settings.AUTH_RATE_LIMIT_PER_IP = "100/hour"

    url = reverse("clients:auth-reset-request")
    body = {"email": "same.person@example.com"}

    assert api_client.post(url, body, format="json").status_code == 202
    assert api_client.post(url, body, format="json").status_code == 202
    limited = api_client.post(url, body, format="json")

    assert limited.status_code == 429
    # The surface renders "try again in N minutes" from this header. Phase 4 of Surface 1
    # found the other half of this bug: the login proxy had no 429 branch, so a working
    # security control was reported as a 502 and read as an outage.
    assert limited.headers.get("Retry-After")


def test_the_per_address_bucket_does_not_punish_a_different_address(api_client, settings):
    settings.AUTH_RATE_LIMIT_ENABLED = True
    settings.AUTH_RATE_LIMIT_PER_ADDRESS = "1/hour"
    settings.AUTH_RATE_LIMIT_PER_IP = "100/hour"

    url = reverse("clients:auth-reset-request")
    assert api_client.post(url, {"email": "one@example.com"}, format="json").status_code == 202
    assert api_client.post(url, {"email": "one@example.com"}, format="json").status_code == 429
    # A different address has its own bucket. Sharing one would make one person's typo
    # everybody's outage.
    assert api_client.post(url, {"email": "two@example.com"}, format="json").status_code == 202


def test_client_login_uses_the_dedicated_auth_throttles(api_client, settings):
    from tests.factories.client_factory import ClientFactory

    settings.ENABLE_CLIENT_PORTAL = True
    settings.AUTH_RATE_LIMIT_ENABLED = True
    settings.AUTH_RATE_LIMIT_PER_ADDRESS = "2/hour"
    settings.AUTH_RATE_LIMIT_PER_IP = "100/hour"

    client = ClientFactory(email="limited-login@example.com")
    client.credential.set_password("correct-password-123")
    client.credential.save(update_fields=["password_hash", "updated_at"])

    url = reverse("clients:client-login")
    body = {"email": client.email, "password": "wrong-password"}
    assert api_client.post(url, body, format="json").status_code == 401
    assert api_client.post(url, body, format="json").status_code == 401
    limited = api_client.post(url, body, format="json")

    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")
