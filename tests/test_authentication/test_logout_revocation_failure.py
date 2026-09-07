from __future__ import annotations

from rest_framework.test import APIRequestFactory

from apps.authentication.views import LogoutView


def test_team_logout_already_invalid_token_is_idempotent():
    request = APIRequestFactory().post(
        "/api/v1/auth/logout/",
        {"refresh": "not-a-valid-jwt"},
        format="json",
    )
    response = LogoutView.as_view()(request)
    assert response.status_code == 205


def test_team_logout_blacklist_storage_failure_is_not_reported_as_success(monkeypatch):
    request = APIRequestFactory().post(
        "/api/v1/auth/logout/",
        {"refresh": "synthetic-refresh"},
        format="json",
    )
    request.correlation_id = "req-team-logout-failure"

    class FakeRefreshToken:
        def __init__(self, _token):
            pass

        def blacklist(self):
            raise RuntimeError("blacklist database detail must stay private")

    monkeypatch.setattr("apps.authentication.views.RefreshToken", FakeRefreshToken)

    response = LogoutView.as_view()(request)
    assert response.status_code == 503
    assert response.data["code"] == "SESSION_REVOCATION_UNAVAILABLE"
    assert response.data["requestId"] == "req-team-logout-failure"
    assert "blacklist database detail" not in str(response.data)
