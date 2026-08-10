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
from apps.clients.backends import ClientJWTAuthentication
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


# ─────────────────────────────────────────────────────────────────────────────
# THE CLIENT PLANE (2026-08-10)
#
# `list_for_client` / `get_for_client` have existed in the service layer since the
# spine shipped, and claiming a thread at signup deliberately REMOVES it from the
# session plane (`client__isnull=True` in every session filter). But no view ever
# authenticated a client, so the moment a thread was claimed it became unreachable:
# the workspace could neither list nor reopen the very conversations signing up
# was supposed to carry over. These views now authenticate the Bearer client-JWT
# when one is presented (the authenticator stays silent otherwise, so the
# anonymous session path is byte-for-byte unchanged) and route ownership to the
# client helpers.
# ─────────────────────────────────────────────────────────────────────────────
def _client_from(request):
    """The authenticated Client, or None on the anonymous plane."""
    from apps.clients.models import Client

    user = getattr(request, "user", None)
    return user if isinstance(user, Client) and user.is_active else None


def _resolve_thread(request, thread_id):
    """One ownership rule for every thread view: client plane first, then session."""
    client = _client_from(request)
    if client is not None:
        owned = thread_svc.get_for_client(thread_id, client)
        if owned is not None:
            return owned
        # Fall through: a signed-in customer opening one of their still-anonymous
        # (pre-signup, same-browser) threads must not be refused for having
        # authenticated.
    return thread_svc.get_for_session(thread_id, visitor_session_from(request))


class ThreadListCreateView(APIView):
    """POST threads/ · GET threads/ — PUBLIC, scoped to the visitor session."""

    permission_classes = [AllowAny]
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request):
        client = _client_from(request)
        if client is not None:
            # The UNION: client-owned threads plus any anonymous threads still on
            # this browser's session — signing in must never make a conversation
            # disappear from the list.
            qs = thread_svc.list_for_client_and_session(client, visitor_session_from(request))[:100]
            return Response(
                {"threads": ThreadSummarySerializer(qs, many=True).data},
                status=status.HTTP_200_OK,
            )
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

        client = _client_from(request)
        session_id = visitor_session_from(request)
        issued_session = False
        if client is None and not session_id:
            session_id = new_visitor_session()
            issued_session = True

        body = data.get("body", "") or ""
        # A signed-in customer's new chat is CLIENT-OWNED from birth — created on
        # the session plane it would vanish from their workspace the way claimed
        # threads used to.
        thread = thread_svc.create_thread(
            visitor_session="" if client is not None else session_id,
            client=client,
            lead=getattr(client, "lead", None) if client is not None else None,
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
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def _load(self, request, thread_id):
        return _resolve_thread(request, thread_id)

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
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
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
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def post(self, request, thread_id):
        session_id = visitor_session_from(request)
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # A signed-in customer may have no visitor session at all; the rate key
        # must still be THEIRS, not one shared empty bucket for every client.
        client = _client_from(request)
        rate_key = session_id or (f"client:{client.id}" if client is not None else "")
        limited = _rate_limited(request, rate_key, "turn")
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
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        from apps.journey.services import shell

        contract = (
            shell.for_subject(thread.lead, thread=thread)
            if thread.lead_id
            else shell.for_anonymous_thread(thread)
        )
        return Response(contract, status=status.HTTP_200_OK)


class ThreadPaneView(APIView):
    """
    GET threads/{id}/pane/ — the content pane's CONTENTS (v7.1 Phase 2).

    ── WHY THIS IS A SEPARATE ENDPOINT FROM shell/ ─────────────────────────
    ``shell/`` authorizes the pane's SECTION LIST — which tabs a subject may see. That is
    enough to stop a visitor at State 2 seeing an ``outcomes`` tab, and it is cheap enough
    to poll.

    It is NOT enough to stop that visitor reading a State 10 artifact whose id they guessed,
    because the artifact read is a different request. So the contents are authorized
    separately, by ``cockpit.services.pane_authorization``, which applies three rules in
    order of how badly each fails:

        1. GOVERNANCE FIRST — not `approved`, not rendered. Whatever its level, whatever
           section asked for it. Under review means a human has not finished deciding.
        2. THE CEILING NEXT — at or below the subject's effective ceiling, which is the
           more restrictive of the plane's cap and the state's. The plane always wins.
        3. THE SECTION LAST — the weakest rule, and deliberately last. If the first two
           hold the content is already safe; this one is presentation.

    Ordering them this way means a bug in the section mapping produces a MISSING artifact
    rather than a leaked one.

    ── AND IT IS SESSION-SCOPED, LIKE EVERY OTHER thread/ ROUTE ────────────
    ``get_for_session`` is the same ownership check the transcript uses. A thread id is not
    a credential: guessing one gets a 404, not a payload.
    """

    permission_classes = [AllowAny]
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from apps.cockpit.services import pane_authorization
        from apps.journey.services import shell

        contract = (
            shell.for_subject(thread.lead, thread=thread)
            if thread.lead_id
            else shell.for_anonymous_thread(thread)
        )

        sections = contract.get("content_pane_sections") or []
        artifacts = pane_authorization.authorized_artifacts(
            thread,
            disclosure_ceiling=contract.get("disclosure_ceiling") or "public",
            sections=sections,
        )

        return Response(
            {
                "thread_id": str(thread.id),
                "content_pane_sections": sections,
                "artifacts": artifacts,
                # Recomputed from the AUTHORIZED list rather than taken from the shell
                # contract: if the default pointed at something the three rules above just
                # removed, honouring it would open the pane onto nothing.
                "content_pane_default_artifact_id": pane_authorization.default_artifact_id(
                    artifacts
                ),
            },
            status=status.HTTP_200_OK,
        )

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
    from apps.conversations.services import conversation_context, ingest
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
        # CONVERSATION MEMORY: prior turns + closed-state summaries + real journey
        # state, so the reply continues the conversation instead of restarting it.
        extra=conversation_context.build_turn_extra(thread, body),
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

    # Internal names never reach a visitor: the prompt teaches the public term, and
    # this is the deterministic guarantee (same shape as the two appends below).
    from apps.conversations.services import terminology

    text = terminology.normalise_outbound(text)

    # If a client page was just revealed for this turn, append the link so the visitor
    # can reach it regardless of whether the live socket delivered the reveal event.
    # (The agent was also told to present it in its own words; the link is the
    # transport-independent guarantee.)
    reveal = getattr(thread, "_client_page_reveal", None)
    if reveal and reveal.get("url") and status == StreamingStatus.SETTLED:
        text = _append_client_page_link(text, reveal["url"])

    # And if the page is waiting on an email address, make sure the reply actually
    # asks for one. The agent was told to ask in its own words; this is the
    # guarantee that the ask happens even with the AI engine off or degraded, which
    # is the difference between a conversation that can complete and one that
    # dead-ends at DIAGNOSED.
    contact_decision = getattr(thread, "_contact_ask", None)
    if contact_decision and status == StreamingStatus.SETTLED:
        from apps.conversations.services import contact_ask

        text = contact_ask.append_ask(text, contact_decision)

    message = ingest.ingest_agent_message(
        thread.conversation,
        agent_key="concierge",
        body=text,
        governance_status=governance_status,
        claim_level=1,
        thread=thread,
        streaming_status=status,
    )

    # COUNT THE ASK DOWN. Only now, and only for a turn the visitor will actually
    # read: an ask held by the guard was never put to anybody and must not spend the
    # budget.
    if contact_decision and status == StreamingStatus.SETTLED:
        from apps.conversations.services import contact_ask

        contact_ask.record_asked(thread, contact_decision, message=message)

    # SUGGEST THE NEXT PROMPT. While the qualification loop is open, generate the
    # follow-up question and broadcast ``question.suggested`` so the composer shows
    # the next-step chips beneath this answer. Skipped once the page is revealed —
    # there is no "next question" after the visitor has been handed their page.
    if not (reveal and reveal.get("revealed")):
        try:
            from apps.conversations.services import qualification

            qualification.suggest_next(thread, message=message)
        except Exception:  # noqa: BLE001
            logger.debug("next-prompt suggestion skipped for thread %s", thread.id)

    return ThreadTurnSerializer(message).data


# ── WHAT HAPPENS AFTER THE PAGE ─────────────────────────────────────────────
# The reveal used to end at the link, so a visitor reached their page and had no idea
# what it was for or what came next — reported as "what happens next after receiving
# personalised page". Three short steps, and honest about the fact that the page is a
# starting point rather than a verdict.
#
# Deterministic copy rather than model-generated: this is a description of the itriX
# engagement path, and a paraphrase that drifted would be a commitment nobody made.
WHAT_HAPPENS_NEXT = (
    "What happens from here: the page reflects the pressure areas you described and "
    "sets out the assessment path that fits them. It is a starting point, not a "
    "verdict — nothing on it is a measured result yet. When you are ready, you can "
    "keep asking questions here, share more about the workload, or ask to speak to "
    "the specialist who reviewed it. Anything workload-specific stays "
    "non-confidential until an NDA is in place."
)


def _append_client_page_link(text: str, url: str) -> str:
    """
    Append the client-page link to a governed reply.

    A bare internal URL carries no claim, so it does not need to pass the claims
    discipline again. One short, plain line so it reads as a hand-off.
    """
    text = (text or "").rstrip()
    if url and url not in text:
        return text + (
            "\n\nYour personalised itriX page is ready — open it here:"
            f"\n\n<{url}>"
            f"\n\n{WHAT_HAPPENS_NEXT}"
        )
    return text
