"""
Token helpers (team plane).

Embed lightweight, non-sensitive identity claims in the JWT so the dashboard could
read them if needed, and so backend code can authorise without an extra DB hit. The
authoritative source remains the DB (resolved via ``/auth/me/``).

v4.0: the team plane's audience is made EXPLICIT (``aud="team"``) so the client plane
(``aud="client"``, issued by ``apps.clients.tokens``) can coexist without a token from
one plane ever validating on the other. SimpleJWT verifies the audience from
``SIMPLE_JWT["AUDIENCE"]`` on decode; we also stamp it on the token here so the claim is
always present regardless of SimpleJWT version behaviour.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

TEAM_AUDIENCE = "team"


def _team_audience() -> str:
    return settings.SIMPLE_JWT.get("AUDIENCE", TEAM_AUDIENCE) or TEAM_AUDIENCE


def build_tokens_for_user(user) -> dict[str, str]:
    """Return a fresh ``{access, refresh}`` pair with itriX claims + team audience."""
    refresh = RefreshToken.for_user(user)
    refresh["aud"] = _team_audience()
    refresh["email"] = user.email
    refresh["name"] = user.display_name
    refresh["role"] = user.role
    refresh["team_role"] = user.team_role
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }
