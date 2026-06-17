"""Permission / role-gating tests on the team endpoints."""

from __future__ import annotations

import pytest

from apps.authentication.tokens import build_tokens_for_user
from tests.factories.user_factory import AdminUserFactory, UserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db

TEAM_URL = "/api/v1/team/"


def _bearer(api_client, user):
    tokens = build_tokens_for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return api_client


def test_team_list_requires_auth(api_client):
    resp = api_client.get(TEAM_URL)
    assert resp.status_code == 401


def test_team_list_visible_to_any_team_member(api_client):
    member = UserFactory()
    _bearer(api_client, member)
    resp = api_client.get(TEAM_URL)
    assert resp.status_code == 200
    # Paginated envelope
    assert "results" in resp.json()


def test_team_patch_allowed_for_admin(api_client):
    admin = AdminUserFactory()
    target = UserFactory()
    _bearer(api_client, admin)
    resp = api_client.patch(
        f"{TEAM_URL}{target.id}/", {"name": "Renamed"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


def test_team_patch_forbidden_for_non_admin(api_client):
    member = UserFactory()  # ASSESSMENT role
    target = UserFactory()
    _bearer(api_client, member)
    resp = api_client.patch(
        f"{TEAM_URL}{target.id}/", {"name": "Nope"}, format="json"
    )
    assert resp.status_code == 403


def test_inactive_user_is_unauthorized(api_client):
    member = UserFactory(is_active=False)
    _bearer(api_client, member)
    resp = api_client.get(TEAM_URL)
    # Inactive users fail authentication entirely.
    assert resp.status_code == 401


def test_viewer_can_read_team(api_client):
    viewer = ViewerUserFactory()
    _bearer(api_client, viewer)
    resp = api_client.get(TEAM_URL)
    assert resp.status_code == 200
