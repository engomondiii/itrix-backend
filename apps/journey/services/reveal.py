"""
Reveal helper (Backend v6.0 §3.1, Architecture v2.6 §11.5).

When a transition lands on a state that unlocks a surface, this builds the reveal
descriptor — including a freshly minted capability token where the surface is reached
via one.

── v6.0: A REVEAL NO LONGER UNLOCKS A PAGE ──────────────────────────────────
In v2.5 a reveal unlocked a destination the visitor had to travel to. In v2.6 it
APPENDS an artifact or a card to the OPEN THREAD and pushes two socket events:

    journey.reveal   { state, state_key, capability_token? }
    shell.update     { journey_state, sidebar_sections, conversation_header,
                       composer_label }

``shell.update`` REPLACES the retired ``rail.update``. Emitting both together is what
makes the open transcript react live without a navigation: the reveal says "something
new is available", the shell update says "and here is what you may now see".

A frontend that responds to a state change by ROUTING is a defect (§11.9).
"""

from __future__ import annotations

import logging

from apps.journey.models import EVENT_REVEAL, STATE_REVEAL, RevealSurface, normalize_state
from apps.journey.services import capability_token as ct

logger = logging.getLogger("itrix")

# Map a reveal surface to the capability-token type that reaches it.
_SURFACE_TOKEN_TYPE = {
    RevealSurface.CLIENT_PAGE.value: ct.TOKEN_CLIENT_PAGE,
    RevealSurface.ACCOUNT_INVITE.value: ct.TOKEN_ACCOUNT_INVITE,
    RevealSurface.PORTAL.value: ct.TOKEN_PORTAL,
    # These are reached INSIDE an authenticated session, never via a public token.
    RevealSurface.DATA_ROOM.value: None,
    RevealSurface.SUCCESS_OVERLAY.value: None,
    RevealSurface.CUSTOMER_SUCCESS_HOME.value: None,
}


def reveal_for_state(lead, state: str) -> dict | None:
    """
    Return a reveal descriptor for ``state`` (or None if the state reveals nothing).

        { "surface": <RevealSurface>, "state": <state>, "capability_token": <str|None> }
    """
    normalized = normalize_state(state)
    surface = STATE_REVEAL.get(normalized)
    if not surface:
        return None
    return _build(lead, surface, normalized)


def reveal_for_event(lead, event: str, state: str) -> dict | None:
    """
    Return a reveal descriptor fired by an EVENT rather than by arriving at a state.

    Reveal 4 (the NDA data room) works this way: the NDA can be signed at any point
    inside NDA_REVIEW, so the state does not change when it fires.
    """
    surface = EVENT_REVEAL.get(event)
    if not surface:
        return None
    return _build(lead, surface, normalize_state(state))


def _build(lead, surface: str, state: str) -> dict:
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
    Push ``journey.reveal`` over the subject's WebSocket group so an open transcript
    learns of a newly unlocked surface in real time.

    Best-effort and optional: when ENABLE_REALTIME is off (or Channels is unavailable)
    this is a no-op and the client discovers the reveal on its next
    ``GET journey/{token}/`` poll instead.
    """
    if not reveal:
        return
    try:
        from apps.conversations.services.fan_out import broadcast_reveal
        from apps.realtime.presence import subject_group

        broadcast_reveal(subject_group(str(lead.id)), reveal)
    except Exception:  # noqa: BLE001 - realtime emit must never break a transition
        logger.debug("journey.reveal emit skipped (realtime unavailable)")


def emit_shell_update(lead, *, thread=None) -> None:
    """
    Push ``shell.update`` — the event that REPLACES ``rail.update``.

    Carries the sidebar section list, the conversation header and the composer label so
    the open conversation re-renders its shell WITHOUT a navigation. Always emitted
    alongside a reveal, and also on any transition that changes what may be rendered.
    """
    try:
        from apps.conversations.services.fan_out import broadcast_shell_update
        from apps.journey.services import shell
        from apps.realtime.presence import subject_group

        contract = shell.for_subject(lead, thread=thread)
        broadcast_shell_update(
            subject_group(str(lead.id)),
            {
                "journey_state": contract["journey_state"],
                "state_key": contract["state_key"],
                "sidebar_sections": contract["sidebar_sections"],
                "conversation_header": contract["conversation_header"],
                "composer_label": contract["composer_label"],
                "question_loop_open": contract["question_loop_open"],
                "attachments_enabled": contract["attachments_enabled"],
                "disclosure_ceiling": contract["disclosure_ceiling"],
                "identity_state": contract["identity_state"],
            },
        )
    except Exception:  # noqa: BLE001 - never break a transition on a fan-out hiccup
        logger.debug("shell.update emit skipped (realtime unavailable)")
