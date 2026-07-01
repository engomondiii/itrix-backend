"""
Presence + fan-out helpers (Channels/Redis groups).

Thin async helpers over the channel layer so consumers stay small. All are safe to call
when Channels is unavailable — they degrade to no-ops — so importing this module never
breaks a non-realtime deployment.

The conversation group name is ``conv.<conversation_id>`` (see Conversation.group_name);
a subject's personal channel (for journey.reveal pushes) is ``subject.<lead_or_client_id>``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")


def subject_group(subject_id: str) -> str:
    return f"subject.{subject_id}"


def conversation_group(conversation_id: str) -> str:
    return f"conv.{conversation_id}"


async def group_add(channel_layer, group: str, channel_name: str) -> None:
    if channel_layer is None:
        return
    await channel_layer.group_add(group, channel_name)


async def group_discard(channel_layer, group: str, channel_name: str) -> None:
    if channel_layer is None:
        return
    await channel_layer.group_discard(group, channel_name)


async def group_send(channel_layer, group: str, event: dict) -> None:
    if channel_layer is None:
        return
    try:
        await channel_layer.group_send(group, event)
    except Exception:  # noqa: BLE001
        logger.exception("presence.group_send failed for %s", group)
