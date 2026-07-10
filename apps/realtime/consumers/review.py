"""
Review + Client-page WebSocket consumers (PUBLIC / anonymous).

    ws/review/{session}/      ReviewConsumer      — the review-chat channel
    ws/client-page/{token}/   ClientPageConsumer  — the customized client page channel

Both authorize via a capability token (client_page / portal) or the review session id,
join the conversation group + the subject group (for journey.reveal pushes), and speak
the frontend's event contract:

    client → server:  { type: "chat.send", payload: { conversationId, body } }
                      { type: "chat.typing", payload: {...} } · { type: "ping" }
    server → client:  { type: "message.delta",        payload: MessageDeltaPayload }
                      { type: "message.final",        payload: { conversationId, message } }
                      { type: "message.under_review", payload: { conversationId, messageId, governanceStatus } }
                      { type: "journey.reveal",       payload: JourneyRevealPayload }
                      { type: "clientpage.delta",     payload: { field, delta } }
                      { type: "clientpage.final",     payload: { page } }
                      { type: "pong",                 payload: {} }

── REAL-TIME GENERATION (v4.0.3) ─────────────────────────────────────────────
Chat replies stream token-by-token: on ``chat.send`` we persist the inbound turn, emit
``message.delta`` for each Claude token, then persist + ``message.final`` the governed
reply. The client page ALSO streams: on connect, ClientPageConsumer streams the "what we
heard" narrative live, then emits ``clientpage.final`` with the fully-normalized page —
so the visitor watches it generate instead of waiting for a background swap or a reload.

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
    """Shared connect/auth/relay logic for the review + client-page channels."""

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

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        payload = content.get("payload") or {}
        if msg_type in ("chat.send", "message.send"):
            body = payload.get("body") if payload else content.get("body", "")
            await self._stream_chat_reply(body or "")
        elif msg_type in ("chat.typing", "typing"):
            pass  # visitor typing is not fanned out on the public plane
        elif msg_type == "clientpage.subscribe" or (
            msg_type == "subscribe" and (payload or {}).get("channel") == "clientpage"
        ):
            # Only the page's live-view connection asks for this, so page generation
            # streams exactly once (not on the chat/journey sockets sharing the URL).
            await self.on_clientpage_subscribe()
        elif msg_type in ("ping", "presence.ping"):
            await self.send_json({"type": "pong", "payload": {}})

    async def on_clientpage_subscribe(self):
        """Hook: ClientPageConsumer streams the page here. Default: nothing."""
        return

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

    # ── sync helpers (DB / agent) ────────────────────────────────────────────
    def _persist_inbound(self, body: str):
        from apps.conversations.services import ingest

        return ingest.ingest_inbound(self.conversation, sender_kind="visitor", body=body)

    def _build_ctx(self, body: str):
        from apps.agents.services.context import PLANE_PUBLIC, AgentContext

        lead = self.conversation.lead
        session = getattr(lead, "review_session", None) if lead else None
        return AgentContext(
            lead_id=str(lead.id) if lead else None,
            prompt=getattr(session, "prompt", "") or body,
            pressures=list(getattr(session, "pressure_areas", []) or []),
            product_route=getattr(lead, "product_route", "general") if lead else "general",
            license_pathway=(
                lead.commercial_path if lead and getattr(lead, "commercial_path", "none") != "none" else None
            ),
            tier=getattr(lead, "tier", 4) if lead else 4,
            plane=PLANE_PUBLIC,
            context_label=self.context_label,
            extra={"message": body},
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
        msg = ingest.ingest_agent_message(
            self.conversation,
            agent_key="concierge",
            body=body_text,
            governance_status=governance_status,
            claim_level=1,
            cited_chunk_ids=[c["chunkId"] for c in citations],
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

                if plc.has_hard_block(text):
                    return "pending", text
                return "auto_approved", plc.scrub(text)
            except Exception:  # noqa: BLE001
                return "auto_approved", text

    # ── conversation resolution (subclass-specific) ──────────────────────────
    async def _resolve_conversation(self):
        return await database_sync_to_async(self._get_conversation)()

    def _get_conversation(self):  # pragma: no cover - overridden
        raise NotImplementedError

    # ── group event relays (server → client), used for cross-process fan-out ──
    async def message_final(self, event):
        await self.send_json({"type": "message.final", "payload": event.get("payload", {})})

    async def message_delta(self, event):
        await self.send_json({"type": "message.delta", "payload": event.get("payload", {})})

    async def message_under_review(self, event):
        await self.send_json({"type": "message.under_review", "payload": event.get("payload", {})})

    async def journey_reveal(self, event):
        # event carries state/surface/capability_token (snake) — reshape to the FE payload.
        await self.send_json(
            {
                "type": "journey.reveal",
                "payload": {
                    "state": event.get("state"),
                    "authorizedSurface": event.get("surface"),
                    "reveal": {
                        "surface": event.get("surface"),
                        "capabilityToken": event.get("capability_token"),
                    },
                    "valueDelivered": bool(event.get("value_delivered", True)),
                    "accountInviteAvailable": bool(event.get("account_invite_available", False)),
                },
            }
        )

    async def presence_update(self, event):
        await self.send_json({"type": "presence.update", "payload": event.get("payload", {})})

    async def team_typing(self, event):
        await self.send_json({"type": "team.typing", "payload": event.get("payload", {})})


class ReviewConsumer(_BaseReviewConsumer):
    context_label = "review"

    def _get_conversation(self):
        from apps.conversations.services.history import (
            get_or_create_client_page_conversation,
            get_or_create_review_conversation,
        )
        from apps.leads.models import Lead

        self.session_id = self.scope["url_route"]["kwargs"].get("session")
        cap = self.scope.get("cap_payload")
        if cap is not None and getattr(cap, "typ", None) in ("client_page", "portal"):
            lead = Lead.objects.filter(id=cap.sub).first()
            if lead is not None:
                return get_or_create_client_page_conversation(lead)
        lead = None
        try:
            _uuid.UUID(str(self.session_id))
            lead = Lead.objects.filter(review_session_id=self.session_id).first()
        except (ValueError, TypeError):
            lead = None
        return get_or_create_review_conversation(review_session_id=self.session_id, lead=lead)


class ClientPageConsumer(_BaseReviewConsumer):
    """ws/client-page/{token}/ — the customized client page channel (live generation)."""

    context_label = "client_page"

    def _get_conversation(self):
        from apps.conversations.services.history import get_or_create_client_page_conversation
        from apps.journey.services import capability_token as ct
        from apps.leads.models import Lead

        token = self.scope["url_route"]["kwargs"].get("token")
        # Prefer the middleware-verified payload; else verify the URL token directly.
        cap = self.scope.get("cap_payload")
        lead = None
        if cap is not None and getattr(cap, "typ", None) in ("client_page", "portal"):
            lead = Lead.objects.filter(id=cap.sub).first()
        if lead is None and token:
            try:
                payload = ct.verify(token, expected_typ=ct.TOKEN_CLIENT_PAGE)
                lead = Lead.objects.filter(id=payload.sub).first()
            except Exception:  # noqa: BLE001
                lead = None
        self.lead = lead
        if lead is None:
            return None
        return get_or_create_client_page_conversation(lead)

    async def on_clientpage_subscribe(self):
        """Stream the client-page generation live, then send the final normalized page."""
        await self._stream_client_page()

    async def _stream_client_page(self):
        lead = getattr(self, "lead", None)
        if lead is None:
            return

        # 1) Is an AI-enriched result already persisted? If so, just send it (fast path).
        already = await database_sync_to_async(self._existing_enriched_page)(lead)
        if already is not None:
            await self.send_json({"type": "clientpage.final", "payload": {"page": already}})
            return

        # 2) Stream the "what we heard" narrative live as the headline generates.
        acc: list[str] = []
        try:
            async for token in _aiter(self._stream_problem_mirror, lead):
                acc.append(token)
                await self.send_json(
                    {"type": "clientpage.delta", "payload": {"field": "problemMirror", "delta": token}}
                )
        except Exception:  # noqa: BLE001
            logger.exception("client-page narrative stream failed")

        # 3) Build + persist the full page (AI where enabled, deterministic otherwise) and
        #    send the normalized final payload so the page snaps to its complete content.
        page = await database_sync_to_async(self._build_and_normalize_page)(lead)
        await self.send_json({"type": "clientpage.final", "payload": {"page": page}})

    def _existing_enriched_page(self, lead):
        from apps.result_page.models import ResultPage

        obj = ResultPage.objects.filter(lead=lead).first()
        if obj is not None and getattr(obj, "used_ai", False):
            return self._build_and_normalize_page(lead)
        return None

    def _stream_problem_mirror(self, lead):
        """A short streamed narrative to show generation immediately (best-effort)."""
        from apps.agents.services.context import PLANE_PUBLIC, AgentContext
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient

        session = getattr(lead, "review_session", None)
        prompt = getattr(session, "prompt", "") or ""
        ctx = AgentContext(
            lead_id=str(lead.id),
            prompt=prompt,
            pressures=list(getattr(session, "pressure_areas", []) or []),
            product_route=lead.product_route,
            tier=lead.tier,
            plane=PLANE_PUBLIC,
            context_label="client_page",
            extra={"message": prompt},
        )
        system = (
            "You are the itriX assessment concierge writing the opening of a customized "
            "review page. In 2-4 warm, precise sentences, restate the visitor's compute "
            "bottleneck in their own terms (the 'problem mirror'). Stay within the claims "
            "discipline: no numbers, no guarantees, no competitor names. Plain prose only."
        )
        user = f"Visitor's described bottleneck:\n{prompt or '(no prompt provided)'}"
        try:
            yield from ClaudeClient().stream(system=system, user=user, max_tokens=300)
        except AIEngineDisabled:
            return

    def _build_and_normalize_page(self, lead) -> dict:
        """Build the client page via the generator and normalize to the ClientPage shape."""
        from apps.result_page.services.result_generator import ResultGenerator

        raw = ResultGenerator().build_client_page(lead, context="public")
        return _normalize_client_page(raw, lead)


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


# ── payload normalization (mirrors the frontend proxy's normalizeClientPage) ─────────
_PRESSURE_LABEL = {
    "cost": "Compute cost growth",
    "speed": "Slow turnaround",
    "energy": "Power / cooling limits",
    "stability_accuracy": "Stability or accuracy drift",
    "memory_data_movement": "Data-movement-bound runtime",
    "hardware_utilization": "Underused accelerators",
    "architecture": "Architectural ceiling",
}


def _s(v, fallback: str = "") -> str:
    return v if isinstance(v, str) else fallback


def _normalize_diagnosis(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    rows = []
    for idx, item in enumerate(items):
        row = item if isinstance(item, dict) else {}
        rel = row.get("relevance")
        relevance = rel if rel in ("high", "medium", "low") else ("high" if idx == 0 else "medium" if idx <= 2 else "low")
        label = _s(row.get("label"))
        if not label:
            pressure = _s(row.get("pressure"))
            label = _PRESSURE_LABEL.get(pressure) or _s(row.get("observation")) or (pressure or "Compute bottleneck")
        rows.append({"label": label, "relevance": relevance})
    return rows


def _normalize_kpis(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        row = item if isinstance(item, dict) else {}
        label = _s(row.get("label")) or _s(row.get("name"))
        metric = _s(row.get("metric")) or _s(row.get("value"))
        if label:
            out.append({"label": label, "metric": metric})
    return out


def _normalize_proofs(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        row = item if isinstance(item, dict) else {}
        title = _s(row.get("title")) or _s(row.get("label"))
        disclosure = "nda_only" if row.get("disclosure") == "nda_only" else "public"
        reference = _s(row.get("reference")) or None
        if title:
            out.append({"title": title, "disclosure": disclosure, "reference": reference})
    return out


def _normalize_slides(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        s = item if isinstance(item, dict) else {}
        disclosure = "controlled_public" if s.get("disclosure") == "controlled_public" else "public"
        title = _s(s.get("title"))
        body = _s(s.get("body"))
        if title or body:
            out.append(
                {
                    "key": _s(s.get("key")) or title or _uuid.uuid4().hex[:8],
                    "title": title,
                    "body": body,
                    "disclosure": disclosure,
                }
            )
    return out


def _normalize_client_page(raw: dict, lead) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    pitch = raw.get("pitch") if isinstance(raw.get("pitch"), dict) else {}

    slides = _normalize_slides(raw.get("slides") or pitch.get("slides"))
    problem_mirror = _s(raw.get("problemMirror")) or _s(pitch.get("headline"))
    diagnosis = _normalize_diagnosis(raw.get("diagnosis"))
    visitor_pain = _s(raw.get("visitorPain")) or problem_mirror or (diagnosis[0]["label"] if diagnosis else "")

    license_raw = raw.get("licensePathway")
    license_pathway = license_raw if license_raw in ("non_exclusive", "exclusive", "strategic") else None

    tier_raw = raw.get("tier")
    try:
        tier = int(tier_raw)
        tier = tier if tier in (1, 2, 3, 4) else 4
    except (TypeError, ValueError):
        tier = 4

    return {
        "token": _s(raw.get("token")),
        "leadId": _s(raw.get("leadId")) or str(getattr(lead, "id", "")),
        "pitchType": _s(raw.get("pitchType")) or _s(pitch.get("pitchType")) or "curious_public",
        "visitorPain": visitor_pain,
        "productRoute": _s(raw.get("productRoute")) or "general",
        "licensePathway": license_pathway,
        "tier": tier,
        "problemMirror": problem_mirror,
        "diagnosis": diagnosis,
        "alphaFitSummary": _s(raw.get("alphaFitSummary")),
        "kpiPreview": _normalize_kpis(raw.get("kpiPreview")),
        "proofPreview": _normalize_proofs(raw.get("proofPreview")),
        "recommendedNextStep": _s(raw.get("recommendedNextStep")),
        "slides": slides,
        "conversationId": _s(raw.get("conversationId")) or (_s(pitch.get("conversationId")) or None),
        "usedAi": raw.get("usedAi") is True or raw.get("used_ai") is True,
    }
