"""Short-lived client-plane WebSocket tickets.

The browser cannot attach the httpOnly client JWT to ``Sec-WebSocket-Protocol`` and
JavaScript must never be given that JWT just to authenticate a socket.  The portal
therefore exchanges its already-authenticated HTTP session for this narrow signed
credential.  It carries only the Client id, is accepted only by the WebSocket auth
middleware, and expires quickly.
"""

from __future__ import annotations

from django.core import signing

WS_TICKET_SALT = "itrix.client-ws.v1"
WS_TICKET_MAX_AGE_SECONDS = 30 * 60


def mint_client_ws_ticket(client) -> str:
    return signing.dumps(
        {
            "v": 2,
            "client_id": str(client.id),
            "session_version": int(getattr(client, "session_version", 0) or 0),
        },
        salt=WS_TICKET_SALT,
        compress=True,
    )


def resolve_client_ws_ticket(ticket: str, *, max_age: int = WS_TICKET_MAX_AGE_SECONDS):
    """Return the active Client named by a valid, unexpired ticket; otherwise ``None``."""
    try:
        payload = signing.loads(ticket, salt=WS_TICKET_SALT, max_age=max_age)
    except signing.BadSignature:
        return None

    if not isinstance(payload, dict) or payload.get("v") not in {1, 2} or not payload.get("client_id"):
        return None

    from apps.clients.models import Client

    client = Client.objects.filter(id=payload["client_id"], is_active=True).first()
    if client is None:
        return None
    # v1 tickets predate the revocation generation and are accepted only before any
    # password/session invalidation. v2 tickets must match the current generation.
    claimed = payload.get("session_version")
    if claimed is None:
        return client if int(getattr(client, "session_version", 0) or 0) == 0 and client.password_changed_at is None else None
    try:
        return client if int(claimed) == int(getattr(client, "session_version", 0) or 0) else None
    except (TypeError, ValueError):
        return None
