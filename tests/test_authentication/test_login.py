"""Login / me / logout / refresh endpoint tests."""

from __future__ import annotations

import pytest

from tests.factories.user_factory import DEFAULT_PASSWORD, AdminUserFactory

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/v1/auth/login/"
ME_URL = "/api/v1/auth/me/"
LOGOUT_URL = "/api/v1/auth/logout/"
REFRESH_URL = "/api/v1/auth/token/refresh/"


def test_login_returns_tokens_and_user(api_client):
    user = AdminUserFactory(email="ada@itrix.example")
    resp = api_client.post(
        LOGIN_URL, {"email": "ada@itrix.example", "password": DEFAULT_PASSWORD}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access" in body and "refresh" in body
    assert body["user"]["email"] == "ada@itrix.example"
    # role is exposed as the friendly display label (team_role)
    assert body["user"]["role"] == user.team_role
    assert body["user"]["permissionRole"] == "ADMIN"


def test_login_is_case_insensitive_on_email(api_client):
    AdminUserFactory(email="caps@itrix.example")
    resp = api_client.post(
        LOGIN_URL, {"email": "CAPS@itrix.example", "password": DEFAULT_PASSWORD}, format="json"
    )
    assert resp.status_code == 200


def test_login_rejects_bad_password(api_client):
    AdminUserFactory(email="bob@itrix.example")
    resp = api_client.post(
        LOGIN_URL, {"email": "bob@itrix.example", "password": "wrong"}, format="json"
    )
    assert resp.status_code == 401
    assert "error" in resp.json()
    assert "detail" in resp.json()["error"]


def test_login_rejects_unknown_user(api_client):
    resp = api_client.post(
        LOGIN_URL, {"email": "nobody@itrix.example", "password": "whatever"}, format="json"
    )
    assert resp.status_code == 401


def test_me_requires_auth(api_client):
    resp = api_client.get(ME_URL)
    assert resp.status_code == 401


def test_me_returns_user_with_bearer(api_client):
    user = AdminUserFactory(email="me@itrix.example")
    login = api_client.post(
        LOGIN_URL, {"email": "me@itrix.example", "password": DEFAULT_PASSWORD}, format="json"
    ).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['access']}")
    resp = api_client.get(ME_URL)
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "me@itrix.example"


def test_token_refresh_issues_new_access(api_client):
    AdminUserFactory(email="ref@itrix.example")
    login = api_client.post(
        LOGIN_URL, {"email": "ref@itrix.example", "password": DEFAULT_PASSWORD}, format="json"
    ).json()
    resp = api_client.post(REFRESH_URL, {"refresh": login["refresh"]}, format="json")
    assert resp.status_code == 200
    assert "access" in resp.json()


def test_logout_blacklists_refresh(api_client):
    AdminUserFactory(email="out@itrix.example")
    login = api_client.post(
        LOGIN_URL, {"email": "out@itrix.example", "password": DEFAULT_PASSWORD}, format="json"
    ).json()
    resp = api_client.post(LOGOUT_URL, {"refresh": login["refresh"]}, format="json")
    assert resp.status_code == 205
    # The blacklisted refresh can no longer be used.
    resp2 = api_client.post(REFRESH_URL, {"refresh": login["refresh"]}, format="json")
    assert resp2.status_code in (401, 400)
