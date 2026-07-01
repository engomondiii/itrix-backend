"""
ClientJWTAuth — the DRF authentication backend for the client plane (audience=client).

It validates a client-JWT (via ``clients.tokens.decode_client_token``, which enforces
``aud="client"``), loads the ``Client``, and returns ``(client, token_payload)``. A
team token — or any token without ``aud="client"`` — is rejected here, so a token from
one plane is never valid on another (Backend v4 §3.1 / §Phase 3 §7).

The returned "user" is the Client instance. It is NOT a Django auth user; client-plane
views use ``IsAuthenticatedClient`` (see permissions.py) rather than the team
permissions, so the two planes never mix.
"""

from __future__ import annotations

import jwt
from rest_framework import authentication, exceptions

from apps.clients.models import Client
from apps.clients.tokens import decode_client_token


class ClientJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None  # no client token presented — let other authenticators try
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header.")

        raw_token = header[1].decode("utf-8")
        try:
            payload = decode_client_token(raw_token)
        except jwt.InvalidAudienceError:
            # Not a client token (likely a team token) — decline rather than fail so
            # the team authenticator can handle it on shared endpoints.
            return None
        except jwt.PyJWTError as exc:
            raise exceptions.AuthenticationFailed(f"Invalid client token: {exc}") from exc

        if payload.get("token_type") != "access":
            raise exceptions.AuthenticationFailed("Not an access token.")

        client = Client.objects.filter(id=payload.get("client_id"), is_active=True).first()
        if client is None:
            raise exceptions.AuthenticationFailed("Client not found or inactive.")

        # Attach the payload so views/permissions can read NDA state without a re-decode.
        request.client_token = payload  # type: ignore[attr-defined]
        return (client, payload)

    def authenticate_header(self, request):
        return self.keyword
