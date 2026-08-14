"""
The anonymous thread consumer — ``ws/review/{thread_id}/`` (Backend v6.0 §7.2).

The public zone previously mounted no chat affordance. It now hosts the PRIMARY
conversation, so the realtime layer must serve UNAUTHENTICATED principals safely.

── WHAT MAKES THIS SAFE ─────────────────────────────────────────────────────
1. SESSION-SCOPED. The consumer authenticates by the signed visitor-session cookie and
   joins a group keyed by thread. An anonymous socket may subscribe ONLY to threads its
   own session owns — checked in the DB query, not in the payload.

2. RATE LIMITED. Per session and per IP on connect and on turn submission, with a
   deterministic, NON-PUNITIVE message when a limit is hit.

3. STREAM GUARDED. Every token is passed through the guard before it is forwarded. On a
   match the stream HALTS, the partial text is DISCARDED via ``message.halted``, and the
   turn is re-routed to the approval queue. This is the only place the halt can actually
   happen, because only the consumer owns the socket.

4. GRACEFUL DEGRADATION. If generation is unavailable the surface falls back to
   request/response with a visible, HONEST indicator. The conversation still works; it
   just does not stream.

── EVENT CONTRACT (Architecture v2.6 §14.3) ─────────────────────────────────
    client -> server   turn.submit    { thread_id, body, attachment_ids[] }
                       turn.cancel    { thread_id, message_id }
                       resume         { last_seq }
    server -> client   message.stage        { threadId, messageId, stage }
    server -> client   message.delta        { thread_id, message_id, token, seq }
                       message.final        { message_id, body, cited_chunk_ids, governance_status }
                       message.under_review { message_id, replacement_body }
                       message.halted       { message_id, reason }
                       shell.update         { journey_state, sidebar_sections, ... }
                       thread.updated       { thread_id, title, state }
"""

from __future__ import annotations

import logging
import uuid as _uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger("itrix")


class ThreadConsumer(AsyncJsonWebsocketConsumer):
    """Serves one Thread on the anonymous plane."""

    thread = None

    # ── connect ──────────────────────────────────────────────────────────────
    async def connect(self):
        self.ack = self.scope.get("ws_subprotocol_ack")
        self.session_id = _session_from_scope(self.scope)
        self.client_ip = _ip_from_scope(self.scope)

        raw_id = self.scope["url_route"]["kwargs"].get("thread_id") or ""
        self.thread = await database_sync_to_async(_resolve_thread)(raw_id, self.session_id)

        if self.thread is None:
            await self._accept()
            await self.close(code=4404)
            return

        decision = await database_sync_to_async(_check_connect)(self.session_id, self.client_ip)
        if decision is not None and decision.blocked:
            await self._accept()
            await self.send_json(
                {"type": "error", "payload": {"reason": decision.reason, "message": decision.message}}
            )
            await self.close(code=4429)
            return

        self.group = f"thread.{self.thread.id}"
        if self.channel_layer is not None:
            await self.channel_layer.group_add(self.group, self.channel_name)

        await self._accept()
        await self._send_shell()

    async def _accept(self):
        if self.ack:
            await self.accept(subprotocol=self.ack)
        else:
            await self.accept()

    async def disconnect(self, code):
        if getattr(self, "group", None) and self.channel_layer is not None:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    # ── receive ──────────────────────────────────────────────────────────────
    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        payload = content.get("payload") or {}

        if msg_type == "turn.submit":
            await self._on_turn_submit(payload)
        elif msg_type == "turn.cancel":
            # Cancellation is advisory in Phase 1: the turn completes SERVER-SIDE so it
            # is never lost, and the client simply stops rendering it. Aborting
            # mid-generation would leave a half-governed message on the record.
            await self.send_json({"type": "turn.cancelled", "payload": payload})
        elif msg_type == "resume":
            await self._on_resume(payload)
        elif msg_type in ("ping", "presence.ping"):
            await self.send_json({"type": "pong", "payload": {}})

    async def _on_turn_submit(self, payload: dict):
        body = (payload.get("body") or "").strip()
        if not body:
            return

        decision = await database_sync_to_async(_check_turn)(self.session_id, self.client_ip)
        if decision is not None and decision.blocked:
            await self.send_json(
                {"type": "error", "payload": {"reason": decision.reason, "message": decision.message}}
            )
            return

        # 1) Persist the visitor turn FIRST. Their words are on the record before any
        #    generation is attempted — a failure downstream must never lose them.
        persisted = await database_sync_to_async(_persist_turn)(self.thread, body)
        if persisted.get("error"):
            await self.send_json(
                {"type": "error", "payload": {"reason": "too_long", "message": persisted["error"]}}
            )
            return

        await self.send_json({"type": "turn.accepted", "payload": persisted["turn"]})

        # 2) Stream the assistant turn under the guard.
        await self._stream_assistant_turn(body)

    async def _stream_assistant_turn(self, body: str):
        from apps.governance.services import stream_guard
        from apps.realtime.services import stage_events

        thread_id = str(self.thread.id)
        message_id = f"a-{_uuid.uuid4().hex[:12]}"

        # v7.1 PHASE 2 — ``message.stage`` (§14.3).
        #
        # Three stages, emitted at REAL pipeline transitions and never on a timer. The
        # emitter deduplicates and refuses a backward move, so an agent that re-queries
        # retrieval mid-generation does not make the indicator look like it has lost its
        # place. If a stage cannot be determined, nothing is sent and the client holds its
        # current label — which is the documented behaviour, not a degraded one.
        stages = stage_events.StageEmitter(
            self.send_json, thread_id=thread_id, message_id=message_id
        )

        # RETRIEVING: before the context is built, because building it is the retrieval.
        await stages.emit(stage_events.STAGE_RETRIEVING)

        ctx = await database_sync_to_async(_build_agent_context)(self.thread, body)
        guard = stream_guard.new_state()
        collected: list[str] = []
        cited_chunk_ids: list[str] = []
        seq = 0
        halted = False

        try:
            from apps.agents.services.concierge import ConciergeAgent

            agent = ConciergeAgent()

            # COMPOSING: the generation call is about to be made.
            await stages.emit(stage_events.STAGE_COMPOSING)

            async for token in _aiter(agent.stream_reply, ctx):
                hit = stream_guard.inspect(guard, token)
                if hit is not None:
                    # HARD STOP. Discard everything already rendered — a prohibited
                    # claim that has been read cannot be un-read, so we do not try to
                    # patch it, we remove it.
                    halted = True
                    await database_sync_to_async(_record_halt)(
                        guard, message_id, thread_id, ctx
                    )
                    await self.send_json(
                        {
                            "type": "message.halted",
                            "payload": stream_guard.halt_payload(
                                guard, thread_id=thread_id, message_id=message_id
                            ),
                        }
                    )
                    break

                seq += 1
                collected.append(token)
                await self.send_json(
                    {
                        "type": "message.delta",
                        "payload": {
                            "threadId": thread_id,
                            "messageId": message_id,
                            "token": token,
                            "seq": seq,
                        },
                    }
                )
            cited_chunk_ids = agent.last_chunk_ids
        except Exception:  # noqa: BLE001
            logger.exception("thread stream failed; falling back to a settled reply")
            collected = []

        if halted:
            return

        # CHECKING: the settle pipeline is starting. This is the last stage and the one a
        # visitor is most likely to see, because settle is where the Claim-Card re-run
        # happens — so it is the stage where saying something true matters most.
        await stages.emit(stage_events.STAGE_CHECKING)

        # 3) SETTLE. The full Claim-Card pipeline runs on the completed message.
        result = await database_sync_to_async(_settle)(
            self.thread, "".join(collected).strip(), ctx, cited_chunk_ids
        )

        if result["under_review"]:
            await self.send_json(
                {
                    "type": "message.under_review",
                    "payload": {
                        "threadId": thread_id,
                        "messageId": result["message_id"] or message_id,
                        "replacementBody": result["replacement_body"],
                    },
                }
            )
            return

        await self.send_json(
            {
                "type": "message.final",
                "payload": {
                    "threadId": thread_id,
                    "messageId": result["message_id"] or message_id,
                    "body": result["body"],
                    "seq": result["seq"],
                    "citedChunkIds": result["cited_chunk_ids"],
                    "governanceStatus": result["governance_status"],
                    "contextNote": result["context_note"],
                    "degraded": result["degraded"],
                },
            }
        )

    async def _on_resume(self, payload: dict):
        last_seq = payload.get("last_seq") or 0
        data = await database_sync_to_async(_resume)(self.thread, last_seq)
        await self.send_json({"type": "resume.replay", "payload": data})

    async def _send_shell(self):
        contract = await database_sync_to_async(_shell_for)(self.thread)
        await self.send_json({"type": "shell.update", "payload": contract})

    # ── group relays ─────────────────────────────────────────────────────────
    async def message_final(self, event):
        await self.send_json({"type": "message.final", "payload": event.get("payload", {})})

    async def message_delta(self, event):
        await self.send_json({"type": "message.delta", "payload": event.get("payload", {})})

    async def message_stage(self, event):
        """
        v7.1 Phase 2. A stage announced from OUTSIDE this consumer.

        The streaming path above emits directly, which is cheaper and ordered. This handler
        exists so a worker or the HTTP turn path can announce a stage to a socket that is
        already open — without it, a visitor whose generation runs on the HTTP path would
        see the indicator hold at its first label for the whole turn.

        The stage is validated here as well as at the emitter: a channel-layer message can
        arrive from any process in the deployment, and an unknown stage would leave the
        client with a label it has no string for.
        """
        from apps.realtime.services import stage_events

        payload = event.get("payload", {}) or {}
        if not stage_events.is_stage(payload.get("stage")):
            return
        await self.send_json({"type": "message.stage", "payload": payload})

    async def message_under_review(self, event):
        await self.send_json({"type": "message.under_review", "payload": event.get("payload", {})})

    async def message_halted(self, event):
        await self.send_json({"type": "message.halted", "payload": event.get("payload", {})})

    async def shell_update(self, event):
        await self.send_json({"type": "shell.update", "payload": event.get("payload", {})})

    async def thread_updated(self, event):
        await self.send_json({"type": "thread.updated", "payload": event.get("payload", {})})

    async def journey_reveal(self, event):
        await self.send_json(
            {
                "type": "journey.reveal",
                "payload": {
                    "state": event.get("state"),
                    "surface": event.get("surface"),
                    "capabilityToken": event.get("capability_token"),
                },
            }
        )

    async def question_suggested(self, event):
        await self.send_json({"type": "question.suggested", "payload": event.get("payload", {})})


# ─────────────────────────────────────────────────────────────────────────────
# Sync helpers (DB / agents), wrapped by the consumer
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_thread(raw_id: str, session_id: str):
    """
    Resolve the URL segment to a Thread OWNED BY THIS SESSION.

    Returns None when the segment is not a uuid, the thread does not exist, or it
    belongs to a different session. All three collapse to the same 4404 close so the
    socket never distinguishes "does not exist" from "not yours".
    """
    from apps.conversations.services import threads as thread_svc

    try:
        _uuid.UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError):
        return None
    return thread_svc.get_for_session(raw_id, session_id)


def _check_connect(session_id: str, ip: str):
    from apps.realtime.services import limits

    return limits.check_connect(session_id=session_id, ip=ip)


def _check_turn(session_id: str, ip: str):
    from apps.realtime.services import limits

    return limits.check_turn(session_id=session_id, ip=ip)


def _persist_turn(thread, body: str) -> dict:
    from apps.conversations.models import MessageTooLong
    from apps.conversations.serializers_thread import ThreadTurnSerializer
    from apps.conversations.services import ingest

    try:
        message = ingest.ingest_inbound(
            thread.conversation, sender_kind="visitor", body=body, thread=thread
        )
    except MessageTooLong as exc:
        return {"error": str(exc)}
    return {"turn": ThreadTurnSerializer(message).data}


def _build_agent_context(thread, body: str):
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext
    from apps.conversations.services import conversation_context

    lead = thread.lead
    session = getattr(lead, "review_session", None) if lead else None
    # IMPORTANT: use the SAME turn-extra builder as the HTTP path.  `ingest_inbound`
    # has already advanced qualification by this point and stashed either
    # `_client_page_reveal` or `_contact_ask` on this exact Thread instance.  Passing
    # a hand-written {message, thread_id} object here used to throw both decisions
    # away on the live WebSocket path, which is why an email could reveal a page in
    # the database while the reply still said it was "being prepared".
    extra = conversation_context.build_turn_extra(thread, body)
    return AgentContext(
        lead_id=str(lead.id) if lead else None,
        prompt=getattr(session, "prompt", "") or body,
        pressures=list(getattr(session, "pressure_areas", []) or []),
        product_route=getattr(lead, "product_route", "general") if lead else "general",
        tier=getattr(lead, "tier", 4) if lead else 4,
        # ALWAYS the public plane on this socket. An anonymous visitor is anonymous
        # regardless of what their thread has reached.
        plane=PLANE_PUBLIC,
        context_label="anonymous_review",
        extra=extra,
    )


def _record_halt(guard, message_id: str, thread_id: str, ctx) -> None:
    from apps.governance.services import stream_guard

    stream_guard.record_hits(
        guard,
        message_id=message_id,
        thread_id=thread_id,
        agent_key="concierge",
        plane=getattr(ctx, "plane", "public"),
    )


def _settle(thread, streamed_text: str, ctx, streamed_cited_chunk_ids=None) -> dict:
    """
    STREAMING GOVERNANCE, PART 3 — settle.

    The full Claim-Card pipeline runs on the completed message exactly as before
    streaming existed. A message that streamed cleanly but FAILS the settle gate is
    replaced by the approved under-review wording: provisional text is always
    replaceable and is never treated as delivered.
    """
    from apps.agents.services.concierge import ConciergeAgent
    from apps.conversations.models import StreamingStatus
    from apps.conversations.services import ingest
    from apps.governance.services.stream_envelope import UNDER_REVIEW_WORDING

    agent = ConciergeAgent()
    cited: list[str] = [c for c in (streamed_cited_chunk_ids or []) if c]
    degraded = False

    if streamed_text:
        body = streamed_text
        status_ = _govern(body, ctx)
        body = status_["text"]
        governance_status = status_["status"]
    else:
        # Nothing streamed — either the engine is off or the envelope refused. Fall back
        # to the deterministic reply rather than leaving the visitor with silence.
        degraded = True
        try:
            out = agent.run(ctx)
            payload = out.payload or {}
            body = payload.get("reply", "") or agent.fallback_reply
            governance_status = out.governance_status
            cited = [c for c in (out.chunk_ids or []) if c]
        except Exception:  # noqa: BLE001
            logger.exception("deterministic concierge reply failed")
            body = agent.fallback_reply
            governance_status = "auto_approved"

    deliverable = governance_status in ("auto_approved", "approved")

    # Transport parity with views_thread + the older review consumer.  The journey
    # decision is deterministic and was made BEFORE generation; the transport owns
    # the final guarantee that the visitor actually receives it.  This makes the
    # email turn atomic from the visitor's perspective: email in -> page link out,
    # with no second email prompt and no model-dependent promise of later work.
    from apps.conversations.services import terminology

    body = terminology.normalise_outbound(body)
    extra = getattr(ctx, "extra", None) or {}
    reveal = extra.get("client_page_reveal") or {}
    if deliverable and reveal.get("url"):
        from apps.conversations.views_thread import _append_client_page_link

        body = _append_client_page_link(body, reveal["url"])

    contact_decision = extra.get("contact_ask") or {}
    if deliverable and contact_decision.get("ask"):
        from apps.conversations.services import contact_ask

        body = contact_ask.append_ask(body, contact_decision)

    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body=body,
        governance_status=governance_status,
        claim_level=1,
        cited_chunk_ids=cited,
        thread=thread,
        streaming_status=(
            StreamingStatus.SETTLED if deliverable else StreamingStatus.UNDER_REVIEW
        ),
    )

    if deliverable and contact_decision.get("ask"):
        from apps.conversations.services import contact_ask

        contact_ask.record_asked(thread, contact_decision, message=message)

    return {
        "message_id": str(message.id),
        "seq": message.seq,
        "body": body if deliverable else "",
        "replacement_body": "" if deliverable else UNDER_REVIEW_WORDING,
        "cited_chunk_ids": cited,
        "governance_status": governance_status,
        "context_note": message.context_note or "",
        "under_review": not deliverable,
        "degraded": degraded,
    }


def _govern(text: str, ctx) -> dict:
    """Run the settle-time governance pass over streamed text."""
    try:
        from apps.agents.services.governance import govern_text

        decision = govern_text(
            text, claim_level=1, context=getattr(ctx, "context_label", "public")
        )
        return {
            "status": decision.get("status", "auto_approved"),
            "text": decision.get("text") or text,
        }
    except Exception:  # noqa: BLE001
        logger.exception("settle-time governance failed; holding conservatively")
        return {"status": "pending", "text": text}


def _resume(thread, last_seq: int) -> dict:
    from apps.realtime.services.sequence import resume_payload

    return resume_payload(thread, last_seq)


def _shell_for(thread) -> dict:
    from apps.journey.services import shell

    if thread.lead_id:
        return shell.for_subject(thread.lead, thread=thread)
    return shell.for_anonymous_thread(thread)


def _session_from_scope(scope) -> str:
    """Read the visitor session from the cookie header or the query string."""
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode(errors="ignore").split(";"):
                key, _, val = part.strip().partition("=")
                if key == "itrix_visitor_session":
                    return val.strip()[:64]
    query = (scope.get("query_string") or b"").decode(errors="ignore")
    for pair in query.split("&"):
        key, _, val = pair.partition("=")
        if key == "session":
            return val.strip()[:64]
    return ""


def _ip_from_scope(scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            return value.decode(errors="ignore").split(",")[0].strip()
    client = scope.get("client") or ()
    return client[0] if client else ""


async def _aiter(gen_func, *args):
    """Drive a blocking generator from the event loop, one item at a time."""
    from asgiref.sync import sync_to_async

    sentinel = object()
    it = await sync_to_async(lambda: gen_func(*args), thread_sensitive=False)()

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
