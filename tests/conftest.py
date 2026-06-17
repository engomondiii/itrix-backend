"""
Shared pytest fixtures.

``api_client`` — unauthenticated DRF client (public Surface 1 calls).
``auth_client`` — DRF client authenticated as a freshly created ADMIN team member.
``team_user`` / ``admin_user`` / ``viewer_user`` — users at each relevant role.

Throttling is disabled during tests so rate limits don't cause flaky failures.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from tests.factories.user_factory import AdminUserFactory, UserFactory, ViewerUserFactory


@pytest.fixture(autouse=True)
def _disable_throttling(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {},
    }


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def admin_user(db):
    return AdminUserFactory()


@pytest.fixture
def team_user(db):
    return UserFactory()


@pytest.fixture
def viewer_user(db):
    return ViewerUserFactory()


@pytest.fixture
def auth_client(db, admin_user) -> APIClient:
    """An APIClient with a valid Bearer token for an ADMIN user."""
    from apps.authentication.tokens import build_tokens_for_user

    client = APIClient()
    tokens = build_tokens_for_user(admin_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client
