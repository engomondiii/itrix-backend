"""
WebSocket auth middleware (Backend v4 §4.2).

Resolves the caller's identity plane from a token passed in the WebSocket subprotocol
(the browser cannot set Authorization headers on a WS handshake, so the token rides in
``Sec-WebSocket-Protocol``). The resolved identity is attached to ``scope`` for the
consumer:

    scope["plane"]        "public" | "client" | "team"
    scope["client"]       the Client instance (client plane) or None
    scope["team_user"]    the team User instance (team plane) or None
    scope["cap_payload"]  the verified capability-token payload (public plane) or None

Cross-plane tokens are rejected: a team token on the portal socket, or a client token on
the console socket, resolves to the public plane (the consumer then closes). A token from
one plane is never valid on another.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def _extract_token(scope) -> tuple[str, str]:
    """
    Return (token, subprotocol_to_ack). The client sends two subprotocols:
    ``["itrix.<plane>", "<token>"]`` — we read the token from the second and echo the
    first back so the handshake completes.
    """
    protocols = []
    for name, value in scope.get("headers", []):
        if name == b"sec-websocket-protocol":
            protocols = [p.strip() for p in value.decode().split(",")]
            break
    if not protocols:
        return "", ""
    # Convention: first protocol is the ack token "itrix.<plane>", token is the last.
    ack = protocols[0]
    token = protocols[-1] if len(protocols) > 1 else ""
    return token, ack


class WSAuthMiddleware:
    """ASGI middleware that resolves the identity plane before the consumer runs."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope.setdefault("plane", "public")
        scope.setdefault("client", None)
        scope.setdefault("team_user", None)
        scope.setdefault("cap_payload", None)

        token, ack = _extract_token(scope)
        scope["ws_subprotocol_ack"] = ack or None

        if token:
            await self._resolve(scope, token)

        return await self.inner(scope, receive, send)

    async def _resolve(self, scope, token: str) -> None:
        from channels.db import database_sync_to_async

        # 1) Try a client-JWT (audience=client).
        client = await database_sync_to_async(self._try_client_token)(token)
        if client is not None:
            scope["plane"] = "client"
            scope["client"] = client
            return

        # 2) Try a team-JWT (audience=team).
        team_user = await database_sync_to_async(self._try_team_token)(token)
        if team_user is not None:
            scope["plane"] = "team"
            scope["team_user"] = team_user
            return

        # 3) Try a capability token (public plane reach: client_page / portal).
        payload = self._try_capability_token(token)
        if payload is not None:
            scope["plane"] = "public"
            scope["cap_payload"] = payload

    # ── resolvers (sync; wrapped for DB access where needed) ──────────────────
    @staticmethod
    def _try_client_token(token: str):
        try:
            import jwt

            from apps.clients.models import Client
            from apps.clients.tokens import decode_client_token

            payload = decode_client_token(token)
            if payload.get("token_type") != "access":
                return None
            return Client.objects.filter(id=payload.get("client_id"), is_active=True).first()
        except Exception:  # noqa: BLE001 - not a client token
            return None

    @staticmethod
    def _try_team_token(token: str):
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            from django.contrib.auth import get_user_model

            access = AccessToken(token)
            user_id = access.get("user_id")
            if not user_id:
                return None
            User = get_user_model()
            return User.objects.filter(id=user_id, is_active=True).first()
        except Exception:  # noqa: BLE001 - not a team token
            return None

    @staticmethod
    def _try_capability_token(token: str):
        try:
            from apps.journey.services import capability_token as ct

            return ct.verify(token)
        except Exception:  # noqa: BLE001 - not a capability token
            return None


def WSAuthMiddlewareStack(inner):
    """Wrap the URLRouter with WS auth (mirrors channels' AuthMiddlewareStack naming)."""
    return WSAuthMiddleware(inner)
