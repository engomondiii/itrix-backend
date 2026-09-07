"""
Review WebSocket consumer (PUBLIC / anonymous).

    ws/review/{session}/      ReviewConsumer      — the review-chat channel

The review channel resolves a browser-bound review session id or an unrelated portal
capability where explicitly allowed.
join the conversation group + the subject group (for journey.reveal pushes), and speak
the frontend's event contract:

    client → server:  { type: "chat.send", payload: { conversationId, body } }
                      { type: "chat.typing", payload: {...} } · { type: "ping" }
    server → client:  { type: "message.delta",        payload: MessageDeltaPayload }
                      { type: "message.final",        payload: { conversationId, message } }
                      { type: "message.under_review", payload: { conversationId, messageId, governanceStatus } }
                      { type: "journey.reveal",       payload: JourneyRevealPayload }
                      { type: "pong",                 payload: {} }

── REAL-TIME GENERATION ───────────────────────────────────────────────────────
Chat replies stream token-by-token: on ``chat.send`` we persist the inbound turn, emit
``message.delta`` for each Claude token, then persist + ``message.final`` the governed
reply. My Review itself is intentionally not streamed over a bearer-token WebSocket; it
is served only after READY through the tokenless BFF/httpOnly-cookie access flow.

All events are wrapped ``{ "type": ..., "payload": {...} }`` and use camelCase keys to
match ``src/lib/realtime/socketEvents.ts`` exactly. Everything degrades safely: if the AI
engine is off, the deterministic reply/page is delivered in one shot.
"""

from __future__ import annotations

import logging
import uuid as _uuid

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.realtime import presence

logger = logging.getLogger("itrix")


class _BaseReviewConsumer(AsyncJsonWebsocketConsumer):
    """Shared connect/auth/relay logic for the review channel."""

    # Subclasses set this to the conversation the socket serves.
    conversation = None

    async def connect(self):
        self.ack = self.scope.get("ws_subprotocol_ack")
        self.conversation = await self._resolve_conversation()
        if self.conversation is None:
            # Accept then close so the browser gets a clean close (not a raw handshake
            # failure that spams the console with reconnect errors).
            if self.ack:
                await self.accept(subprotocol=self.ack)
            else:
                await self.accept()
            await self.close(code=4404)
            return

        self.group = presence.conversation_group(str(self.conversation.id))
        await presence.group_add(self.channel_layer, self.group, self.channel_name)

        self.subject_group = None
        if self.conversation.lead_id:
            self.subject_group = presence.subject_group(str(self.conversation.lead_id))
            await presence.group_add(self.channel_layer, self.subject_group, self.channel_name)

        # ── AND THE THREAD GROUP ────────────────────────────────────────────────
        # Five broadcasts are addressed to `thread.<id>` rather than `conv.<id>`:
        # `thread.updated` (ingest, claim), `shell.update` (thread_state,
        # reveal_bridge), `question.suggested` (qualification) and `journey.reveal`
        # (reveal_bridge). This socket only ever joined the conversation group, so
        # every one of them was sent to a group with no members and silently
        # dropped.
        #
        # What that cost, concretely: a new conversation never received its
        # generated title, so the rail showed a bare "4m ago"; the composer never
        # received its next-step chips; the shell contract never refreshed on a
        # state change; and the personalised-page reveal never reached
        # `useClientPageReveal`, which is why the "View your page" button never
        # appeared even when the page was ready.
        self.thread_group = None
        thread_group = await self._thread_group()
        if thread_group:
            self.thread_group = thread_group
            await presence.group_add(self.channel_layer, self.thread_group, self.channel_name)

        if self.ack:
            await self.accept(subprotocol=self.ack)
        else:
            await self.accept()

        await self.on_connected()

    async def on_connected(self):
        """Hook for subclasses (e.g. stream the client page). Default: nothing."""
        return

    async def disconnect(self, code):
        if getattr(self, "group", None):
            await presence.group_discard(self.channel_layer, self.group, self.channel_name)
        if getattr(self, "subject_group", None):
            await presence.group_discard(self.channel_layer, self.subject_group, self.channel_name)
        if getattr(self, "thread_group", None):
            await presence.group_discard(self.channel_layer, self.thread_group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        payload = content.get("payload") or {}
        if msg_type in ("chat.send", "message.send"):
            body = payload.get("body") if payload else content.get("body", "")
            await self._stream_chat_reply(body or "")
        elif msg_type in ("chat.typing", "typing"):
            pass  # visitor typing is not fanned out on the public plane
        elif msg_type in ("ping", "presence.ping"):
            await self.send_json({"type": "pong", "payload": {}})

    # ── chat: stream a governed reply token-by-token ─────────────────────────
    async def _stream_chat_reply(self, body: str):
        body = (body or "").strip()
        if not body:
            return

        conv = self.conversation
        conv_id = str(conv.id)

        # 1) persist the visitor turn.
        await database_sync_to_async(self._persist_inbound)(body)

        # 2) stream the agent reply.
        message_id = f"a-{_uuid.uuid4().hex[:12]}"
        ctx = await database_sync_to_async(self._build_ctx)(body)

        acc: list[str] = []
        try:
            from apps.agents.services.concierge import ConciergeAgent

            agent = ConciergeAgent()
            # Drive the blocking generator in a worker thread, forwarding each delta.
            async for token in _aiter(agent.stream_reply, ctx):
                acc.append(token)
                await self.send_json(
                    {
                        "type": "message.delta",
                        "payload": {
                            "conversationId": conv_id,
                            "messageId": message_id,
                            "delta": token,
                            "senderKind": "agent",
                            "agentKey": "concierge",
                        },
                    }
                )
        except Exception:  # noqa: BLE001
            logger.exception("chat stream failed; falling back to one-shot reply")
            acc = []

        streamed_text = "".join(acc).strip()

        # 3) finalize: govern the streamed text (or run the deterministic reply if empty).
        result = await database_sync_to_async(self._finalize_reply)(streamed_text, ctx)

        if result["under_review"]:
            await self.send_json(
                {
                    "type": "message.under_review",
                    "payload": {
                        "conversationId": conv_id,
                        "messageId": message_id,
                        "governanceStatus": result["governance_status"],
                    },
                }
            )
            return

        await self.send_json(
            {
                "type": "message.final",
                "payload": {
                    "conversationId": conv_id,
                    "message": {
                        "id": result["message_id"] or message_id,
                        "conversationId": conv_id,
                        "senderKind": "agent",
                        "agentKey": "concierge",
                        "body": result["body"],
                        "citations": result["citations"],
                        "governanceStatus": result["governance_status"],
                        "streaming": False,
                        "createdAt": result["created_at"],
                    },
                },
            }
        )

        # SUGGEST THE NEXT PROMPT. While the qualification loop is open, generate and
        # broadcast the follow-up question so the composer shows next-step chips. The
        # broadcast reaches this same socket group, so the visitor sees it live.
        await database_sync_to_async(self._suggest_next)()

    def _suggest_next(self):
        thread = getattr(self.conversation, "thread", None)
        if thread is None:
            return
        # No "next question" after the page has been handed over.
        if getattr(thread, "_client_page_reveal", None):
            return
        try:
            from apps.conversations.services import qualification

            qualification.suggest_next(thread)
        except Exception:  # noqa: BLE001
            logger.debug("next-prompt suggestion skipped for thread %s", getattr(thread, "id", "?"))

    # ── sync helpers (DB / agent) ────────────────────────────────────────────
    def _persist_inbound(self, body: str):
        from apps.conversations.services import ingest

        return ingest.ingest_inbound(self.conversation, sender_kind="visitor", body=body)

    def _build_ctx(self, body: str):
        from apps.agents.services.context import PLANE_PUBLIC, AgentContext
        from apps.conversations.services import conversation_context

        lead = self.conversation.lead
        session = getattr(lead, "review_session", None) if lead else None
        thread = getattr(self.conversation, "thread", None)
        # CONVERSATION MEMORY: the same assembler the HTTP path uses, so a streamed
        # reply sees prior turns + closed-state summaries + real journey state and
        # continues the conversation instead of restarting it. Falls back to a bare
        # {"message": body} when the thread has no memory yet.
        extra = (
            conversation_context.build_turn_extra(thread, body)
            if thread is not None
            else {"message": body}
        )
        return AgentContext(
            lead_id=str(lead.id) if lead else None,
            prompt=getattr(session, "prompt", "") or body,
            pressures=list(getattr(session, "pressure_areas", []) or []),
            product_route=getattr(lead, "product_route", "undetermined") if lead else "undetermined",
            license_pathway=(
                lead.commercial_path if lead and getattr(lead, "commercial_path", "none") != "none" else None
            ),
            tier=getattr(lead, "tier", 4) if lead else 4,
            plane=PLANE_PUBLIC,
            context_label=self.context_label,
            extra=extra,
        )

    def _finalize_reply(self, streamed_text: str, ctx) -> dict:
        """
        Persist + govern the final reply. If streaming produced text, govern it directly
        (fast: no second model call). Otherwise run the deterministic concierge reply.
        """
        from apps.agents.services.concierge import ConciergeAgent
        from apps.conversations.services import ingest

        agent = ConciergeAgent()
        citations: list[dict] = []

        if streamed_text:
            body_text = streamed_text
            governance_status, body_text = self._govern(body_text, ctx)
        else:
            out = agent.run(ctx)  # AI one-shot or deterministic fallback (governed by runtime)
            payload = out.payload or {}
            body_text = payload.get("reply", "") or agent.fallback_reply
            governance_status = out.governance_status
            citations = [{"chunkId": c, "label": None} for c in (out.chunk_ids or []) if c]

        deliverable = governance_status in ("auto_approved", "approved")

        # Internal names never reach a visitor (mirror of views_thread; the streamed
        # text may have carried the term for a moment, but the settled message that
        # replaces it in the transcript — and the record — does not).
        from apps.conversations.services import terminology

        body_text = terminology.normalise_outbound(body_text)

        # And the mirror image: when the page is waiting on an email address, make
        # sure the reply asks for one. The agent was told to ask in its own words;
        # this guarantees the ask survives a degraded or model-free turn, so a
        # streamed conversation cannot dead-end at DIAGNOSED either.
        contact_decision = (getattr(ctx, "extra", None) or {}).get("contact_ask") or {}
        if deliverable and contact_decision.get("ask"):
            from apps.conversations.services import contact_ask

            body_text = contact_ask.append_ask(body_text, contact_decision)

        msg = ingest.ingest_agent_message(
            self.conversation,
            agent_key="concierge",
            body=body_text,
            governance_status=governance_status,
            claim_level=1,
            cited_chunk_ids=[c["chunkId"] for c in citations],
        )

        # Count the ask down only for a turn the visitor will actually read.
        if deliverable and contact_decision.get("ask"):
            from apps.conversations.services import contact_ask

            contact_ask.record_asked(
                getattr(self.conversation, "thread", None), contact_decision, message=msg
            )
        return {
            "message_id": str(msg.id),
            "body": body_text if deliverable else "",
            "citations": citations,
            "governance_status": governance_status,
            "under_review": not deliverable,
            "created_at": msg.created_at.isoformat(),
        }

    @staticmethod
    def _govern(text: str, ctx) -> tuple[str, str]:
        """Run the governance pass over streamed text; return (status, possibly-scrubbed text)."""
        try:
            from apps.agents.services.governance import govern_text

            decision = govern_text(text, claim_level=1, context=getattr(ctx, "context_label", "public"))
            status = decision.get("status", "auto_approved")
            out_text = decision.get("text") or text
            return status, out_text
        except Exception:  # noqa: BLE001 - never fail delivery on a governance hiccup
            logger.exception("govern of streamed text failed; delivering conservatively")
            # Conservative: scrub obvious prohibited language locally, still deliver.
            try:
                from apps.ai_engine.services import prohibited_language_checker as plc

                return "auto_approved", plc.scrub(text)
            except Exception:  # noqa: BLE001
                return "auto_approved", text

    # ── conversation resolution (subclass-specific) ──────────────────────────
    async def _resolve_conversation(self):
        return await database_sync_to_async(self._get_conversation)()

    def _get_conversation(self):  # pragma: no cover - overridden
        raise NotImplementedError

    async def _thread_group(self):
        """The thread group for this conversation, or None when it has no thread."""
        from channels.db import database_sync_to_async

        return await database_sync_to_async(self._thread_group_sync)()

    def _thread_group_sync(self):
        thread = getattr(self.conversation, "thread", None)
        return getattr(thread, "group_name", None) if thread is not None else None

    # ── group event relays (server → client), used for cross-process fan-out ──
    async def message_final(self, event):
        await self.send_json({"type": "message.final", "payload": event.get("payload", {})})

    async def message_delta(self, event):
        await self.send_json({"type": "message.delta", "payload": event.get("payload", {})})

    async def message_under_review(self, event):
        await self.send_json({"type": "message.under_review", "payload": event.get("payload", {})})

    async def journey_reveal(self, event):
        # Client-page/My Review reveals expose ONLY the browser-bound one-time
        # accessCode. Other surfaces retain their legitimate capabilityToken contract.
        surface = event.get("surface")
        reveal_payload = {"surface": surface}
        if surface == "client_page":
            reveal_payload["accessCode"] = event.get("access_code")
        elif event.get("capability_token"):
            reveal_payload["capabilityToken"] = event.get("capability_token")
        await self.send_json(
            {
                "type": "journey.reveal",
                "payload": {
                    "state": event.get("state"),
                    "authorizedSurface": surface,
                    "reveal": reveal_payload,
                    "valueDelivered": bool(event.get("value_delivered", True)),
                    "accountInviteAvailable": bool(event.get("account_invite_available", False)),
                },
            }
        )

    async def presence_update(self, event):
        await self.send_json({"type": "presence.update", "payload": event.get("payload", {})})

    async def team_typing(self, event):
        await self.send_json({"type": "team.typing", "payload": event.get("payload", {})})

    # ── The relays that were missing ─────────────────────────────────────────
    # Channels dispatches a group event to the method named after its type with the
    # dots turned into underscores. With no method, the frame is not merely ignored:
    # the consumer raises "No handler for message type ...", which is both a lost
    # event and a line of noise in the server log for every occurrence.
    #
    # Each of these has a live sender in the codebase and a live handler on the
    # frontend. They were the gap in between.

    async def thread_updated(self, event):
        """Title, state or ownership changed — the rail re-labels and re-orders."""
        await self.send_json({"type": "thread.updated", "payload": event.get("payload", {})})

    async def shell_update(self, event):
        """A fresh shell contract after a state move."""
        await self.send_json({"type": "shell.update", "payload": event.get("payload", {})})

    async def question_suggested(self, event):
        """The next question and its chips, for the composer."""
        await self.send_json({"type": "question.suggested", "payload": event.get("payload", {})})

    async def artifact_ready(self, event):
        """A governed artifact is available in this thread."""
        await self.send_json({"type": "artifact.ready", "payload": event.get("payload", {})})

    async def message_stage(self, event):
        """A real pipeline transition — the pending indicator's only input."""
        await self.send_json({"type": "message.stage", "payload": event.get("payload", {})})

    async def message_halted(self, event):
        """The guard stopped a message. The client discards what it rendered."""
        await self.send_json({"type": "message.halted", "payload": event.get("payload", {})})

    async def attachment_status(self, event):
        """An attachment finished, failed or was rejected."""
        await self.send_json({"type": "attachment.status", "payload": event.get("payload", {})})


class ReviewConsumer(_BaseReviewConsumer):
    context_label = "review"

    def _get_conversation(self):
        from apps.conversations.services.history import get_or_create_review_conversation
        from apps.leads.models import Lead

        self.session_id = self.scope["url_route"]["kwargs"].get("session")
        cap = self.scope.get("cap_payload")
        # My Review client_page bearer capabilities are retired. An unrelated portal
        # capability may still resolve a lead for this historical review-chat surface.
        if cap is not None and getattr(cap, "typ", None) == "portal":
            lead = Lead.objects.filter(id=cap.sub).first()
            if lead is not None:
                return get_or_create_review_conversation(review_session_id=str(lead.review_session_id), lead=lead)
        lead = None
        try:
            _uuid.UUID(str(self.session_id))
            lead = Lead.objects.filter(review_session_id=self.session_id).first()
        except (ValueError, TypeError):
            lead = None
        return get_or_create_review_conversation(review_session_id=self.session_id, lead=lead)




# ── async iteration helper: run a blocking generator in a thread, yield to the loop ──
async def _aiter(gen_func, *args):
    """
    Turn a blocking generator function into an async iterator by pulling one item at a
    time in a worker thread. Keeps the event loop free while Claude streams.
    """
    sentinel = object()

    def _make():
        return gen_func(*args)

    it = await sync_to_async(_make, thread_sensitive=False)()

    def _next():
        try:
            return next(it)
        except StopIteration:
            return sentinel

    while True:
        item = await sync_to_async(_next, thread_sensitive=False)()
        if item is sentinel:
            break
        yield item
