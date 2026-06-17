"""
Token helpers.

Embed lightweight, non-sensitive identity claims in the JWT so the dashboard could
read them if needed, and so backend code can authorise without an extra DB hit. The
authoritative source remains the DB (resolved via ``/auth/me/``).
"""

from __future__ import annotations

from rest_framework_simplejwt.tokens import RefreshToken


def build_tokens_for_user(user) -> dict[str, str]:
    """Return a fresh ``{access, refresh}`` pair with itriX claims attached."""
    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    refresh["name"] = user.display_name
    refresh["role"] = user.role
    refresh["team_role"] = user.team_role
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }
