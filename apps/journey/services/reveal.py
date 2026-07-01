"""
Reveal helper.

When a transition lands on a state that unlocks a surface (client_page, account_invite,
portal, data_room), this builds the reveal descriptor — including a freshly minted
capability token where the surface is reached via one. The WebSocket layer (Phase 3)
emits this as ``journey.reveal``; in Phase 1 it is returned by the journey GET endpoint.
"""

from __future__ import annotations

from apps.journey.models import RevealSurface, STATE_REVEAL
from apps.journey.services import capability_token as ct

# Map a reveal surface to the capability-token type that reaches it.
_SURFACE_TOKEN_TYPE = {
    RevealSurface.CLIENT_PAGE: ct.TOKEN_CLIENT_PAGE,
    RevealSurface.ACCOUNT_INVITE: ct.TOKEN_ACCOUNT_INVITE,
    RevealSurface.PORTAL: ct.TOKEN_PORTAL,
    # data_room is reached inside the authenticated portal, not via a public token.
    RevealSurface.DATA_ROOM: None,
}


def reveal_for_state(lead, state: str) -> dict | None:
    """
    Return a reveal descriptor for ``state`` (or None if the state reveals nothing).

        { "surface": <RevealSurface>, "state": <state>, "capability_token": <str|None> }
    """
    surface = STATE_REVEAL.get(state)
    if not surface:
        return None

    token_type = _SURFACE_TOKEN_TYPE.get(surface)
    token = None
    if token_type is not None:
        single_use = token_type == ct.TOKEN_ACCOUNT_INVITE
        ttl = None
        if token_type == ct.TOKEN_ACCOUNT_INVITE:
            from django.conf import settings

            ttl = int(getattr(settings, "ACCOUNT_INVITE_TTL_HOURS", 72)) * 3600
        token = ct.mint(
            sub=str(lead.id),
            typ=token_type,
            state=state,
            ttl_seconds=ttl,
            single_use=single_use,
        )

    return {"surface": surface, "state": state, "capability_token": token}


def emit_reveal(lead, reveal: dict | None) -> None:
    """
    Push a ``journey.reveal`` over the subject's WebSocket group so the client learns of
    a newly unlocked surface in real time. Best-effort and optional: when ENABLE_REALTIME
    is off (or Channels is unavailable) this is a no-op and the client discovers the
    reveal on its next ``GET journey/{token}/`` poll instead.
    """
    if not reveal:
        return
    try:
        from apps.conversations.services.fan_out import broadcast_reveal
        from apps.realtime.presence import subject_group

        broadcast_reveal(subject_group(str(lead.id)), reveal)
    except Exception:  # noqa: BLE001 - realtime emit must never break a transition
        pass
