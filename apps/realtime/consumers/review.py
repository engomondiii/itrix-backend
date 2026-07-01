"""
Review WebSocket consumer — ws/review/{session}/ (PUBLIC / anonymous).

The anonymous visitor's live channel during the review + on the customized client page.
It authorizes via a capability token (client_page/portal) OR the session id itself, joins
the conversation group + the subject group (for journey.reveal pushes), and relays:

    client → server:  message.send · typing · presence.ping
    server → client:  message.delta · message.final · message.under_review · journey.reveal

Message handling delegates to the review-chat service (persist + route to Concierge),
so the WS path and the REST fallback share one code path. Everything degrades safely:
if ENABLE_REALTIME is off the socket is simply never mounted.
"""

from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.realtime import presence

logger = logging.getLogger("itrix")


class ReviewConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"].get("session")
        self.ack = self.scope.get("ws_subprotocol_ack")
        self.conversation = await self._resolve_conversation()
        if self.conversation is None:
            await self.close(code=4404)
            return

        self.group = presence.conversation_group(str(self.conversation.id))
        await presence.group_add(self.channel_layer, self.group, self.channel_name)

        # Subject group for reveal pushes (keyed by the lead id when present).
        self.subject_group = None
        if self.conversation.lead_id:
            self.subject_group = presence.subject_group(str(self.conversation.lead_id))
            await presence.group_add(self.channel_layer, self.subject_group, self.channel_name)

        # Accept, echoing the ack subprotocol so the browser handshake completes.
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

        # Persist + route to Concierge (governed). Returns the agent reply message row.
        await database_sync_to_async(self._persist_and_reply)(body)

    def _persist_and_reply(self, body: str):
        from apps.review.services.review_chat import handle_review_chat_turn

        return handle_review_chat_turn(
            review_session_id=self.session_id,
            lead=self.conversation.lead,
            body=body,
        )

    async def _resolve_conversation(self):
        from channels.db import database_sync_to_async

        return await database_sync_to_async(self._get_conversation)()

    def _get_conversation(self):
        from apps.conversations.services.history import (
            get_or_create_client_page_conversation,
            get_or_create_review_conversation,
        )
        from apps.leads.models import Lead

        cap = self.scope.get("cap_payload")
        # If a client_page capability token is presented, use the lead's client-page thread.
        if cap is not None and cap.typ in ("client_page", "portal"):
            lead = Lead.objects.filter(id=cap.sub).first()
            if lead is not None:
                return get_or_create_client_page_conversation(lead)
        # Otherwise fall back to the review thread keyed by session id.
        lead = None
        try:
            import uuid as _uuid

            _uuid.UUID(str(self.session_id))
            lead = Lead.objects.filter(review_session_id=self.session_id).first()
        except (ValueError, TypeError):
            lead = None
        return get_or_create_review_conversation(review_session_id=self.session_id, lead=lead)

    # ── group event handlers (server → client) ────────────────────────────────
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
