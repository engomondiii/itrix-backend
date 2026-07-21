"""
Thread views — the ``threads/`` route family (Backend v6.0 §7.1).

    POST   threads/                    create a thread                     PUBLIC
    GET    threads/                    list THIS SESSION's threads         PUBLIC
    GET    threads/{id}/               thread + shell contract             PUBLIC
    PATCH  threads/{id}/               rename                              PUBLIC
    DELETE threads/{id}/               delete (visitor-initiated)          PUBLIC
    GET    threads/{id}/messages/      paginated transcript                PUBLIC
    POST   threads/{id}/turns/         submit a turn                       PUBLIC

"PUBLIC" here means UNAUTHENTICATED, not UNPROTECTED. Every route is scoped to the
signed visitor session that owns the thread, in the QUERY. An anonymous visitor can only
ever reach threads their own session created.

── THE SESSION IS THE AUTHORIZATION ─────────────────────────────────────────
There is no thread-id-is-secret assumption anywhere here. URL obscurity is never
authorization (§11.9). Guessing a thread id gets you a 404 because the query filters on
your session, not because the id was hard to guess.
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.conversations.models import Message, MessageTooLong
from apps.conversations.serializers_thread import (
    ThreadCreateSerializer,
    ThreadDetailSerializer,
    ThreadRenameSerializer,
    ThreadSummarySerializer,
    ThreadTurnSerializer,
    TurnSubmitSerializer,
)
from apps.conversations.services import threads as thread_svc

logger = logging.getLogger("itrix")

VISITOR_SESSION_COOKIE = "itrix_visitor_session"
VISITOR_SESSION_HEADER = "HTTP_X_ITRIX_SESSION"


def visitor_session_from(request) -> str:
    """
    Resolve the caller's visitor session.

    Header first so a server-side proxy can forward it explicitly without depending on
    cookie passthrough; cookie second for a direct browser call.
    """
    header = request.META.get(VISITOR_SESSION_HEADER, "") or ""
    if header.strip():
        return header.strip()[:64]
    return (request.COOKIES.get(VISITOR_SESSION_COOKIE, "") or "").strip()[:64]


def new_visitor_session() -> str:
    """A fresh opaque session id. Not derived from anything about the visitor."""
    return secrets.token_urlsafe(24)[:48]


def _set_session_cookie(response, session_id: str):
    """
    Attach the visitor-session cookie.

    httpOnly so client JS cannot read it, SameSite=Lax so it survives a same-site
    navigation, Secure in production. The retention window matches the thread retention
    window, so the cookie never outlives the data it points at.
    """
    days = thread_svc.anon_retention_days()
    response.set_cookie(
        VISITOR_SESSION_COOKIE,
        session_id,
        max_age=days * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        path="/",
    )
    return response


def _rate_limited(request, session_id: str, kind: str):
    """Apply the anonymous-plane rate limits. Returns a Response when blocked."""
    from apps.realtime.services import limits

    ip = (request.META.get("HTTP_X_FORWARDED_FOR", "") or request.META.get("REMOTE_ADDR", "") or "")
    ip = ip.split(",")[0].strip()
    decision = limits.check_turn(session_id=session_id, ip=ip) if kind == "turn" else None
    if decision is not None and decision.blocked:
        return Response(
            {"detail": decision.message, "reason": decision.reason},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after_seconds or 60)},
        )
    return None


class ThreadListCreateView(APIView):
    """POST threads/ · GET threads/ — PUBLIC, scoped to the visitor session."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        session_id = visitor_session_from(request)
        if not session_id:
            # No session means no threads. Not an error — a first-time visitor.
            return Response({"threads": []}, status=status.HTTP_200_OK)
        qs = thread_svc.list_for_session(session_id)[:100]
        return Response(
            {"threads": ThreadSummarySerializer(qs, many=True).data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        ser = ThreadCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        session_id = visitor_session_from(request)
        issued_session = False
        if not session_id:
            session_id = new_visitor_session()
            issued_session = True

        body = data.get("body", "") or ""
        thread = thread_svc.create_thread(
            visitor_session=session_id,
            title=thread_svc.derive_title(body) if body else "",
        )

        # The FIRST PROMPT IS THE FIRST REVIEW TURN (R12). If the visitor typed
        # something when creating the thread, it is persisted as turn 1 here — there is
        # no screen anywhere that asks them to restate the sentence they already typed.
        if body.strip():
            try:
                self._persist_first_turn(thread, body)
            except MessageTooLong as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            # The first sentence deserves an answer in the same response. Waiting
            # for a socket that may never connect is how a visitor concludes the
            # surface is broken.
            _generate_assistant_turn(thread, body)
            thread.refresh_from_db()

        payload = ThreadDetailSerializer(thread).data
        response = Response(payload, status=status.HTTP_201_CREATED)
        if issued_session:
            _set_session_cookie(response, session_id)
        return response

    @staticmethod
    def _persist_first_turn(thread, body: str):
        from apps.conversations.services import ingest

        return ingest.ingest_inbound(
            thread.conversation,
            sender_kind="visitor",
            body=body,
            thread=thread,
        )


class ThreadDetailView(APIView):
    """GET/PATCH/DELETE threads/{id}/ — PUBLIC, scoped to the visitor session."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def _load(self, request, thread_id):
        return thread_svc.get_for_session(thread_id, visitor_session_from(request))

    def get(self, request, thread_id):
        thread = self._load(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ThreadDetailSerializer(thread).data, status=status.HTTP_200_OK)

    def patch(self, request, thread_id):
        thread = self._load(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        ser = ThreadRenameSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        thread = thread_svc.rename(thread, ser.validated_data["title"])
        return Response(ThreadSummarySerializer(thread).data, status=status.HTTP_200_OK)

    def delete(self, request, thread_id):
        """
        Visitor-initiated delete.

        The visitor can remove a thread at any time. Phase 2 extends this to purge the
        attachments and their extractions too (§19.7 rule 8); Phase 1 removes the thread
        and its turns.
        """
        thread = self._load(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        conversation_id = thread.conversation_id
        thread.delete()
        if conversation_id:
            from apps.conversations.models import Conversation

            Conversation.objects.filter(id=conversation_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ThreadMessagesView(APIView):
    """GET threads/{id}/messages/ — paginated transcript."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, thread_id):
        thread = thread_svc.get_for_session(thread_id, visitor_session_from(request))
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            after = int(request.query_params.get("after_seq", 0))
        except (TypeError, ValueError):
            after = 0
        try:
            limit = min(int(request.query_params.get("limit", 200)), 500)
        except (TypeError, ValueError):
            limit = 200

        qs = Message.objects.filter(thread=thread, seq__gt=after).order_by("seq", "created_at")[:limit]
        return Response(
            {
                "threadId": str(thread.id),
                "messages": ThreadTurnSerializer(qs, many=True).data,
                "latestSeq": Message.objects.filter(thread=thread).count() and max(
                    (m.seq for m in Message.objects.filter(thread=thread).only("seq")), default=0
                ),
            },
            status=status.HTTP_200_OK,
        )


class ThreadTurnsView(APIView):
    """
    POST threads/{id}/turns/ — submit a turn.

    Returns the persisted USER turn immediately. The assistant turn streams over the
    socket; when the socket is unavailable the client falls back to polling
    ``messages/``. Either way the visitor's own words are on the record before anything
    else happens — that is the one thing that must not depend on a working socket.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, thread_id):
        session_id = visitor_session_from(request)
        thread = thread_svc.get_for_session(thread_id, session_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        limited = _rate_limited(request, session_id, "turn")
        if limited is not None:
            return limited

        ser = TurnSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from apps.conversations.services import ingest

        try:
            message = ingest.ingest_inbound(
                thread.conversation,
                sender_kind="visitor",
                body=ser.validated_data["body"],
                thread=thread,
                meta={"attachment_ids": ser.validated_data.get("attachment_ids", [])},
            )
        except MessageTooLong as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        # Generate the reply here too. The socket streams it when connected; this
        # guarantees an answer when it is not. See _generate_assistant_turn.
        assistant = _generate_assistant_turn(thread, ser.validated_data["body"])

        return Response(
            {
                "threadId": str(thread.id),
                "turn": ThreadTurnSerializer(message).data,
                # Null ONLY when generation was genuinely unavailable. The client
                # then shows its honest degraded state rather than a fabricated
                # answer.
                "assistantTurn": assistant,
            },
            status=status.HTTP_201_CREATED,
        )


class ThreadShellView(APIView):
    """GET threads/{id}/shell/ — just the shell contract, for a cheap re-render."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, thread_id):
        thread = thread_svc.get_for_session(thread_id, visitor_session_from(request))
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        from apps.journey.services import shell

        contract = (
            shell.for_subject(thread.lead, thread=thread)
            if thread.lead_id
            else shell.for_anonymous_thread(thread)
        )
        return Response(contract, status=status.HTTP_200_OK)

# ─────────────────────────────────────────────────────────────────────────────
# Assistant generation on the HTTP path (v6.0 delivery fix)
# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 generated replies ONLY in the WebSocket consumer, on ``turn.submit``.
# That is the right place for STREAMING — but it made the answer depend entirely
# on a socket handshake succeeding, and when the handshake failed the visitor got
# their own words back and nothing else. No error, no explanation: just silence
# where the reply should be.
#
# A conversation surface whose answer requires a working WebSocket has a single
# point of failure in the one interaction that matters. So the HTTP path now
# generates too:
#
#   * socket connected   -> it streams, and this returns the settled turn
#   * socket unavailable  -> this still answers, in one piece
#
# The reply is GOVERNED IDENTICALLY either way — same envelope, same guard, same
# settle. Generation being reachable from two transports must never mean two
# standards of review.


def _generate_assistant_turn(thread, body: str):
    """
    Produce the assistant reply for a turn, governed.

    Returns a serialized turn dict, or None when generation is unavailable — in
    which case the caller says so honestly rather than fabricating an answer.
    """
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext
    from apps.conversations.models import StreamingStatus
    from apps.conversations.services import ingest
    from apps.governance.services import stream_envelope, stream_guard

    lead = getattr(thread, "lead", None)
    session = getattr(lead, "review_session", None) if lead else None

    ctx = AgentContext(
        lead_id=str(lead.id) if lead else None,
        prompt=getattr(session, "prompt", "") or body,
        pressures=list(getattr(session, "pressure_areas", []) or []),
        product_route=getattr(lead, "product_route", "general") if lead else "general",
        tier=getattr(lead, "tier", 4) if lead else 4,
        # ALWAYS the public plane on this route. An anonymous visitor is
        # anonymous regardless of what their thread has reached.
        plane=PLANE_PUBLIC,
        context_label="anonymous_review",
        extra={"message": body, "thread_id": str(thread.id)},
    )

    # PART 1 — the pre-flight envelope. A turn that would require level-4 or -5
    # approval never renders provisionally, on this path either.
    envelope = stream_envelope.for_context(ctx, intended_claim_level=1)

    text = ""
    degraded = False
    if envelope.may_stream:
        try:
            from apps.agents.services.concierge import ConciergeAgent

            agent = ConciergeAgent()
            out = agent.run(ctx)
            payload = out.payload or {}
            text = (payload.get("reply") or "").strip() or agent.fallback_reply
        except Exception:  # noqa: BLE001
            logger.exception("assistant generation failed for thread %s", thread.id)
            degraded = True
    else:
        text = envelope.replacement_body

    if degraded or not text:
        return None

    # PART 2 — the guard, applied to the completed text. On this path there is no
    # partial render to discard, so a hit replaces rather than halts.
    hits = stream_guard.scan(text)
    if hits:
        logger.warning(
            "assistant reply held by the guard on thread %s (%s)",
            thread.id, ", ".join(sorted({h.category for h in hits})),
        )
        text = stream_envelope.UNDER_REVIEW_WORDING
        status = StreamingStatus.UNDER_REVIEW
        governance_status = "pending"
    else:
        # PART 3 — settle.
        try:
            from apps.agents.services.governance import govern_text

            decision = govern_text(text, claim_level=1, context="anonymous_review")
            governance_status = decision.get("status", "auto_approved")
            text = decision.get("text") or text
        except Exception:  # noqa: BLE001
            logger.exception("settle-time governance unavailable; holding")
            governance_status = "pending"
        deliverable = governance_status in ("auto_approved", "approved")
        status = StreamingStatus.SETTLED if deliverable else StreamingStatus.UNDER_REVIEW
        if not deliverable:
            text = stream_envelope.UNDER_REVIEW_WORDING

    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body=text,
        governance_status=governance_status,
        claim_level=1,
        thread=thread,
        streaming_status=status,
    )
    return ThreadTurnSerializer(message).data
