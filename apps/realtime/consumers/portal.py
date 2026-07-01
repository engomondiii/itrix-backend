"""
Portal WebSocket consumer — ws/portal/ (CLIENT plane, client-JWT).

The authenticated client's live channel inside the portal. Requires a client-JWT
(resolved by the ws_auth middleware to ``scope["client"]``); anything else is refused.
Joins the client's primary portal conversation group + their subject group, and relays
the same message/typing/presence/reveal protocol as the review socket. Team→client
messages arriving via the console fan out to this socket (governed).
"""

from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.realtime import presence

logger = logging.getLogger("itrix")


class PortalConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.client = self.scope.get("client")
        self.ack = self.scope.get("ws_subprotocol_ack")
        if self.scope.get("plane") != "client" or self.client is None:
            await self.close(code=4401)  # unauthorized — client plane required
            return

        self.conversation = await self._resolve_conversation()
        self.group = presence.conversation_group(str(self.conversation.id))
        await presence.group_add(self.channel_layer, self.group, self.channel_name)
        self.subject_group = presence.subject_group(str(self.client.id))
        await presence.group_add(self.channel_layer, self.subject_group, self.channel_name)

        if self.ack:
            await self.accept(subprotocol=self.ack)
        else:
            await self.accept()

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await presence.group_discard(self.channel_layer, self.group, self.channel_name)
        if getattr(self, "subject_group", None):
            await presence.group_discard(self.channel_layer, self.subject_group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "message.send":
            await self._handle_send(content.get("body", ""))
        elif msg_type == "typing":
            await presence.group_send(
                self.channel_layer, self.group, {"type": "team.typing", "conversation_id": str(self.conversation.id)}
            )
        elif msg_type == "presence.ping":
            await self.send_json({"type": "presence.pong"})

    async def _handle_send(self, body: str):
        from channels.db import database_sync_to_async

        await database_sync_to_async(self._persist_and_reply)(body)

    def _persist_and_reply(self, body: str):
        from apps.conversations.services import fan_out, ingest
        from apps.conversations.services.history import mark_read

        inbound = ingest.ingest_inbound(
            self.conversation, sender_kind="client", body=body, client=self.client
        )
        fan_out.broadcast_message(inbound)
        mark_read(self.conversation, client=self.client)

        # Route to the Concierge for a governed reply (portal context, NDA-aware).
        from apps.agents.services.context import AgentContext, PLANE_CLIENT
        from apps.agents.services.runtime import run_concierge

        lead = self.client.lead
        ctx = AgentContext(
            lead_id=str(lead.id) if lead else None,
            client_id=str(self.client.id),
            prompt=getattr(getattr(lead, "review_session", None), "prompt", "") or "",
            product_route=getattr(lead, "product_route", "general"),
            tier=getattr(lead, "tier", 4),
            plane=PLANE_CLIENT,
            nda_signed=self.client.nda_signed,
            context_label="portal",
            extra={"message": body},
        )
        out = run_concierge(ctx)
        reply = ingest.ingest_agent_message(
            self.conversation,
            agent_key="concierge",
            body=(out.payload or {}).get("reply", ""),
            governance_status=out.governance_status,
            claim_level=out.claim_level,
            cited_chunk_ids=out.chunk_ids,
        )
        fan_out.broadcast_message(reply)
        return reply

    async def _resolve_conversation(self):
        from channels.db import database_sync_to_async

        return await database_sync_to_async(self._get_conversation)()

    def _get_conversation(self):
        from apps.conversations.services.history import get_or_create_portal_conversation

        return get_or_create_portal_conversation(self.client)

    # ── group event handlers ──────────────────────────────────────────────────
    async def message_final(self, event):
        await self.send_json({**event, "type": "message.final"})

    async def message_delta(self, event):
        await self.send_json({**event, "type": "message.delta"})

    async def message_under_review(self, event):
        await self.send_json({**event, "type": "message.under_review"})

    async def journey_reveal(self, event):
        await self.send_json({**event, "type": "journey.reveal"})

    async def presence_update(self, event):
        await self.send_json({**event, "type": "presence.update"})

    async def team_typing(self, event):
        await self.send_json({**event, "type": "team.typing"})
