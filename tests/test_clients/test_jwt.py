"""Client-JWT: mint + decode with audience=client; cross-plane rejection."""

from __future__ import annotations

import jwt
import pytest

from apps.clients.tokens import CLIENT_AUDIENCE, build_tokens_for_client, decode_client_token
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def test_mint_and_decode_client_token():
    client = ClientFactory()
    tokens = build_tokens_for_client(client)
    payload = decode_client_token(tokens["access"])
    assert payload["aud"] == CLIENT_AUDIENCE
    assert payload["client_id"] == str(client.id)
    assert payload["token_type"] == "access"


def test_team_audience_token_is_rejected_on_client_plane(settings):
    # A token minted with the team audience must fail client decode (wrong audience).
    client = ClientFactory()
    import time

    from django.conf import settings as dj

    bad = jwt.encode(
        {"aud": "team", "client_id": str(client.id), "exp": int(time.time()) + 60},
        getattr(dj, "CLIENT_JWT_SIGNING_KEY", dj.SECRET_KEY),
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidAudienceError):
        decode_client_token(bad)


def test_client_backend_authenticates(settings):
    from rest_framework.test import APIRequestFactory

    from apps.clients.backends import ClientJWTAuthentication

    client = ClientFactory()
    tokens = build_tokens_for_client(client)
    req = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    user, payload = ClientJWTAuthentication().authenticate(req)
    assert user == client
    assert payload["client_id"] == str(client.id)
