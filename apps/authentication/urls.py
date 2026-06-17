"""Authentication URL routes (mounted under /api/v1/auth/)."""

from __future__ import annotations

from django.urls import path

from apps.authentication.views import (
    ITrixTokenRefreshView,
    LoginView,
    LogoutView,
    MeView,
)

app_name = "authentication"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("token/refresh/", ITrixTokenRefreshView.as_view(), name="token-refresh"),
]
