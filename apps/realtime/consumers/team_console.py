"""
Team console WebSocket consumer — ws/console/ (TEAM plane, team-JWT).

The internal operator's live channel. Requires a team-JWT (resolved to
``scope["team_user"]``). The console can subscribe to any conversation group to watch
agent/client traffic and post team→client messages (governed like any outbound message).
Phase 2 wires connect/subscribe/relay; the full approval-queue actions land in Phase 3.
"""

from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.realtime import presence

logger = logging.getLogger("itrix")


class TeamConsoleConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.team_user = self.scope.get("team_user")
        self.ack = self.scope.get("ws_subprotocol_ack")
        if self.scope.get("plane") != "team" or self.team_user is None:
            await self.close(code=4401)
            return
        self.groups_joined: set[str] = set()
        if self.ack:
            await self.accept(subprotocol=self.ack)
        else:
            await self.accept()

    async def disconnect(self, code):
        for group in list(getattr(self, "groups_joined", set())):
            await presence.group_discard(self.channel_layer, group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "subscribe":
            conv_id = content.get("conversation_id")
            if conv_id:
                group = presence.conversation_group(str(conv_id))
                await presence.group_add(self.channel_layer, group, self.channel_name)
                self.groups_joined.add(group)
                await self.send_json({"type": "subscribed", "conversation_id": conv_id})
        elif msg_type == "message.send":
            await self._handle_team_message(content.get("conversation_id"), content.get("body", ""))
        elif msg_type == "typing":
            conv_id = content.get("conversation_id")
            if conv_id:
                await presence.group_send(
                    self.channel_layer,
                    presence.conversation_group(str(conv_id)),
                    {"type": "team.typing", "conversation_id": str(conv_id)},
                )

    async def _handle_team_message(self, conversation_id, body: str):
        if not conversation_id:
            return
        from channels.db import database_sync_to_async

        await database_sync_to_async(self._persist_team_message)(conversation_id, body)

    def _persist_team_message(self, conversation_id, body: str):
        from apps.conversations.models import Conversation
        from apps.conversations.services import fan_out, ingest

        conv = Conversation.objects.filter(id=conversation_id).first()
        if conv is None:
            return None
        msg = ingest.ingest_team_message(conv, user=self.team_user, body=body)
        fan_out.broadcast_message(msg)
        return msg

    # ── group event handlers ──────────────────────────────────────────────────
    async def message_final(self, event):
        await self.send_json({**event, "type": "message.final"})

    async def message_under_review(self, event):
        await self.send_json({**event, "type": "message.under_review"})

    async def presence_update(self, event):
        await self.send_json({**event, "type": "presence.update"})

    async def team_typing(self, event):
        await self.send_json({**event, "type": "team.typing"})

    async def approval_new(self, event):
        await self.send_json({**event, "type": "approval.new"})
