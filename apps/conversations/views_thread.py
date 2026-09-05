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

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass

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


def _request_id(request) -> str:
    """Correlation id assigned by RequestLoggingMiddleware, when available."""
    return str(getattr(request, "correlation_id", "") or "")[:128]


def _safe_error_response(request, *, code: str, detail: str, status_code: int, headers=None, **extra):
    """One public-safe conversation error shape.

    The browser receives a stable category and correlation id, never backend internals.
    Existing callers that only read ``detail`` remain compatible.
    """
    payload = {"detail": detail, "code": code, **extra}
    request_id = _request_id(request)
    if request_id:
        payload["requestId"] = request_id
    return Response(payload, status=status_code, headers=headers or {})


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


def _bind_attachments(request, thread, attachment_ids) -> list[str]:
    """
    Move the caller's UNBOUND attachments onto ``thread``, and report which are there.

    The list is filtered by the UPLOADER inside ``intake.bind_many``, so an id belonging
    to another session is skipped rather than bound. An id that is already on this thread
    is returned as-is, which makes a retried submit idempotent; an id on a DIFFERENT
    thread is refused, because binding must never carry a document between conversations.

    Never raises. Attachments are an enhancement to a turn; the turn is the thing that
    must not fail.
    """
    if not attachment_ids:
        return []
    try:
        from apps.attachments.permissions import uploader_id_for
        from apps.attachments.services import intake

        return intake.bind_many(
            attachment_ids, thread, uploaded_by_id=uploader_id_for(request)
        )
    except Exception:  # noqa: BLE001
        logger.exception("attachment binding failed for thread %s", getattr(thread, "id", "?"))
        return []


def _rate_limited(request, session_id: str, kind: str):
    """Apply the anonymous-plane rate limits. Returns a Response when blocked."""
    from apps.realtime.services import limits

    ip = (request.META.get("HTTP_X_FORWARDED_FOR", "") or request.META.get("REMOTE_ADDR", "") or "")
    ip = ip.split(",")[0].strip()
    decision = limits.check_turn(session_id=session_id, ip=ip) if kind == "turn" else None
    if decision is not None and decision.blocked:
        return _safe_error_response(
            request,
            code="RATE_LIMITED",
            detail=decision.message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after_seconds or 60)},
            reason=decision.reason,
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


def _creation_idempotency(request, data) -> tuple[str | None, str]:
    """Return (stored key digest, canonical payload digest) for a first-turn request.

    The raw key never enters a row or a log. The payload digest binds a key to exactly
    one request so a buggy caller cannot reuse a recovery identifier for different text.
    """
    raw = (request.META.get("HTTP_IDEMPOTENCY_KEY", "") or "").strip()
    if not raw:
        return None, ""
    if len(raw) > 128:
        raise ValueError("Idempotency-Key is too long.")
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    canonical = json.dumps(
        {
            "body": data.get("body", "") or "",
            "example_key": data.get("example_key", "") or "",
            "attachment_ids": list(data.get("attachment_ids") or []),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return key_hash, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_created_thread(request, *, key_hash: str, payload_hash: str, client, session_id: str):
    """Resolve an already-created first request without repeating any business effect.

    If the original anonymous response was lost before its Set-Cookie reached the browser,
    the caller may have no session yet. Possession of the high-entropy idempotency key is
    accepted only for that no-session recovery case; an existing *different* session may
    not cross into the thread.
    """
    from apps.conversations.models import Thread

    thread = Thread.objects.select_related("conversation", "lead", "client").filter(
        creation_idempotency_hash=key_hash
    ).first()
    if thread is None:
        return None, False
    if thread.creation_payload_hash != payload_hash:
        return Response(
            {"detail": "That idempotency key was already used for a different request."},
            status=status.HTTP_409_CONFLICT,
        ), False

    if client is not None:
        if thread.client_id != client.id:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND), False
        return thread, False

    if thread.client_id is not None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND), False
    if session_id and thread.visitor_session != session_id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND), False

    # True means the caller lost the original response (and therefore its cookie).
    return thread, not bool(session_id)


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

        try:
            idempotency_hash, payload_hash = _creation_idempotency(request, data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if idempotency_hash:
            replay, recover_session = _replay_created_thread(
                request, key_hash=idempotency_hash, payload_hash=payload_hash,
                client=client, session_id=session_id,
            )
            if isinstance(replay, Response):
                return replay
            if replay is not None:
                response = Response(ThreadDetailSerializer(replay).data, status=status.HTTP_200_OK)
                response["Idempotency-Replayed"] = "true"
                if recover_session and replay.visitor_session:
                    _set_session_cookie(response, replay.visitor_session)
                return response

        if client is None and not session_id:
            session_id = new_visitor_session()
            issued_session = True

        body = data.get("body", "") or ""
        # The first sentence is a turn too. It must consume the same abuse budget as a
        # subsequent POST /turns/ so opening a fresh chat can never be used to step around
        # the turn limiter. Idempotency replay happens above this point and therefore does
        # not spend the budget a second time.
        if body.strip():
            rate_key = session_id or (f"client:{client.id}" if client is not None else "")
            limited = _rate_limited(request, rate_key, "turn")
            if limited is not None:
                logger.info(
                    "conversation.rate_limited request_id=%s phase=thread_create actor=%s",
                    _request_id(request),
                    hashlib.sha256(rate_key.encode("utf-8")).hexdigest()[:12] if rate_key else "none",
                )
                return limited

        # A signed-in customer's new chat is CLIENT-OWNED from birth — created on
        # the session plane it would vanish from their workspace the way claimed
        # threads used to.
        thread = thread_svc.create_thread(
            visitor_session="" if client is not None else session_id,
            client=client,
            lead=getattr(client, "lead", None) if client is not None else None,
            title=thread_svc.derive_title(body) if body else "",
            creation_idempotency_hash=idempotency_hash,
            creation_payload_hash=payload_hash,
        )

        # ── THE HAND-OFF THIS SERIALIZER WAS ALWAYS FOR (2026-08-13) ──────────
        # `attachment_ids` has been declared on ThreadCreateSerializer since v6.0 and was
        # never read, so a file attached on the arrival screen was silently dropped: it
        # stayed unbound, no MessageAttachment row was written, and `excerpts.for_context`
        # — which selects by THREAD — never saw it. The visitor watched their document
        # upload and then got an answer that ignored it.
        #
        # Binding happens BEFORE the first turn is persisted, because the turn is what the
        # files are linked to and the answer generated below reads them off the thread.
        bound_ids = _bind_attachments(request, thread, data.get("attachment_ids") or [])

        # The FIRST PROMPT IS THE FIRST REVIEW TURN (R12). If the visitor typed
        # something when creating the thread, it is persisted as turn 1 here — there is
        # no screen anywhere that asks them to restate the sentence they already typed.
        if body.strip():
            try:
                first = self._persist_first_turn(thread, body)
            except MessageTooLong as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            if bound_ids:
                from apps.conversations.services import ingest

                ingest.associate_attachments(first, bound_ids)
            # The first sentence deserves an answer in the same response. Waiting
            # for a socket that may never connect is how a visitor concludes the
            # surface is broken.
            attempt = _attempt_assistant_generation(thread, body, request_id=_request_id(request))
            thread.refresh_from_db()
        else:
            attempt = GenerationAttempt(state="ready", turn=None)

        payload = ThreadDetailSerializer(thread).data
        payload["generationStatus"] = attempt.state
        if attempt.state == "failed":
            payload["generationError"] = {
                "code": "MODEL_GENERATION_FAILED",
                "detail": "Your message was saved, but we could not generate a response just now.",
                "retryable": True,
            }
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
            logger.info(
                "conversation.thread_inaccessible request_id=%s thread_id=%s method=GET",
                _request_id(request), thread_id,
            )
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return Response(ThreadDetailSerializer(thread).data, status=status.HTTP_200_OK)

    def patch(self, request, thread_id):
        thread = self._load(request, thread_id)
        if thread is None:
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
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
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
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
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

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
            logger.info(
                "conversation.turn_inaccessible request_id=%s thread_id=%s",
                _request_id(request), thread_id,
            )
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # A signed-in customer may have no visitor session at all; the rate key
        # must still be THEIRS, not one shared empty bucket for every client.
        client = _client_from(request)
        rate_key = session_id or (f"client:{client.id}" if client is not None else "")
        limited = _rate_limited(request, rate_key, "turn")
        if limited is not None:
            logger.info(
                "conversation.rate_limited request_id=%s phase=thread_turn thread_id=%s actor=%s",
                _request_id(request),
                thread_id,
                hashlib.sha256(rate_key.encode("utf-8")).hexdigest()[:12] if rate_key else "none",
            )
            return limited

        ser = TurnSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from apps.conversations.services import ingest

        # Bind first, link after the message exists. Files attached in the composer of an
        # ALREADY-OPEN thread are staged unbound too (the composer does not re-send a
        # thread id it was not given), so the same hand-off applies here.
        requested_ids = ser.validated_data.get("attachment_ids", [])
        bound_ids = _bind_attachments(request, thread, requested_ids)

        try:
            message = ingest.ingest_inbound(
                thread.conversation,
                sender_kind="visitor",
                body=ser.validated_data["body"],
                thread=thread,
                meta={"attachment_ids": bound_ids},
            )
        except MessageTooLong as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        # The link the transcript renders. `associate_attachments` re-checks that every id
        # is on THIS thread, so a foreign id in the list costs that file and nothing else.
        if bound_ids:
            ingest.associate_attachments(message, bound_ids)

        # Generate the reply here too. The socket streams it when connected; this
        # guarantees an answer when it is not. See _generate_assistant_turn.
        attempt = _attempt_assistant_generation(
            thread, ser.validated_data["body"], request_id=_request_id(request)
        )

        payload = {
            "threadId": str(thread.id),
            "turn": ThreadTurnSerializer(message).data,
            "assistantTurn": attempt.turn,
            "generationStatus": attempt.state,
        }
        if attempt.state == "failed":
            payload["generationError"] = {
                "code": "MODEL_GENERATION_FAILED",
                "detail": "Your message was saved, but we could not generate a response just now.",
                "retryable": True,
            }
        return Response(payload, status=status.HTTP_201_CREATED)


class ThreadRetryView(APIView):
    """POST threads/{id}/retry/ — retry the latest unanswered visitor turn safely."""

    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication]

    def post(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        visitor = (
            Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
            .order_by("-seq", "-created_at")
            .first()
        )
        if visitor is None:
            return Response({"detail": "There is no turn to retry."}, status=status.HTTP_409_CONFLICT)
        existing = (
            Message.objects.filter(thread=thread, sender_kind="agent", seq__gt=visitor.seq)
            .order_by("seq", "created_at")
            .first()
        )
        if existing is not None:
            return Response({"assistantTurn": ThreadTurnSerializer(existing).data, "reused": True}, status=status.HTTP_200_OK)
        attempt = _attempt_assistant_generation(thread, visitor.body, request_id=_request_id(request))
        if attempt.state == "pending":
            return Response(
                {"pending": True, "code": "GENERATION_ALREADY_IN_PROGRESS"},
                status=status.HTTP_202_ACCEPTED,
            )
        if attempt.state == "failed":
            return _safe_error_response(
                request,
                code="MODEL_GENERATION_FAILED",
                detail="Your message is saved, but response generation failed. Please try again.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                retryable=True,
            )
        return Response({"assistantTurn": attempt.turn, "reused": False}, status=status.HTTP_200_OK)


class ThreadShellView(APIView):
    """GET threads/{id}/shell/ — just the shell contract, for a cheap re-render."""

    permission_classes = [AllowAny]
    # Populates request.user from a Bearer client-JWT when present; silent otherwise.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
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


@dataclass(frozen=True)
class GenerationAttempt:
    """Outcome of one idempotent attempt to produce the assistant turn."""

    # ``ready`` means ``turn`` is the settled assistant turn; ``pending`` means another
    # request owns the generation lock; ``failed`` means this attempt acquired the lock
    # but generation did not produce a deliverable response.
    state: str
    turn: dict | None = None


def _attempt_assistant_generation(thread, body: str, *, request_id: str = "") -> GenerationAttempt:
    """Idempotent transport-independent generation with an explicit outcome.

    HTTP and retry paths share this lock. A retry while the original generation is
    still running therefore cannot create a second assistant/business action, while a
    genuine provider/governance failure is no longer confused with that in-progress case.
    """
    from django.core.cache import cache

    latest = (
        Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
        .order_by("-seq", "-created_at")
        .only("seq")
        .first()
    )
    seq = getattr(latest, "seq", 0) or 0
    key = f"itrix:turn-generation:{thread.id}:{seq}"
    if not cache.add(key, "1", timeout=180):
        return GenerationAttempt(state="pending")
    try:
        # Recheck after taking the lock: another request may have completed between
        # the caller's read and this acquisition.
        existing = (
            Message.objects.filter(thread=thread, sender_kind="agent", seq__gt=seq)
            .order_by("seq", "created_at")
            .first()
        )
        if existing is not None:
            return GenerationAttempt(state="ready", turn=ThreadTurnSerializer(existing).data)
        generated = _generate_assistant_turn_impl(thread, body, request_id=request_id)
        if generated is None:
            return GenerationAttempt(state="failed")
        return GenerationAttempt(state="ready", turn=generated)
    finally:
        cache.delete(key)


def _generate_assistant_turn(thread, body: str):
    """Compatibility wrapper for call sites that only need the turn-or-None contract."""
    attempt = _attempt_assistant_generation(thread, body)
    return attempt.turn if attempt.state == "ready" else None


def _generate_assistant_turn_impl(thread, body: str, *, request_id: str = ""):
    """
    Produce the assistant reply for a turn, governed.

    Returns a serialized turn dict, or None when generation is unavailable — in
    which case the caller says so honestly rather than fabricating an answer.
    """
    from apps.agents.services.context import PLANE_PUBLIC, AgentContext
    from apps.conversations.models import StreamingStatus
    from apps.conversations.services import conversation_context, ingest
    from apps.governance.services import stream_envelope

    lead = getattr(thread, "lead", None)
    session = getattr(lead, "review_session", None) if lead else None

    # v2.2 hard stops run before retrieval/model invocation. The correct response to
    # confidential input or protected-function probing is deliberately smaller than a
    # normal answer, and it must not contain the sensitive values from the visitor turn.
    from apps.conversations.services import confidentiality, protected_probe
    if getattr(thread, "_confidential_intercept", None):
        text = confidentiality.safe_reply(locale=getattr(thread, "locale", "en"))
        message = ingest.ingest_agent_message(
            thread.conversation, agent_key="concierge", body=text, governance_status="auto_approved",
            claim_level=0, thread=thread, streaming_status=StreamingStatus.SETTLED,
            meta={"policy_stop": "confidential_input"},
        )
        return ThreadTurnSerializer(message).data
    if getattr(thread, "_protected_probe", False):
        text = protected_probe.safe_reply(locale=getattr(thread, "locale", "en"))
        message = ingest.ingest_agent_message(
            thread.conversation, agent_key="concierge", body=text, governance_status="auto_approved",
            claim_level=0, thread=thread, streaming_status=StreamingStatus.SETTLED,
            meta={"policy_stop": "protected_probe"},
        )
        return ThreadTurnSerializer(message).data

    ctx = AgentContext(
        lead_id=str(lead.id) if lead else None,
        prompt=getattr(session, "prompt", "") or body,
        pressures=list(getattr(session, "pressure_areas", []) or []),
        product_route=getattr(lead, "product_route", "undetermined") if lead else "undetermined",
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
    can_continue = False
    cited_chunk_ids: list[str] = []
    if envelope.may_stream:
        try:
            from apps.agents.services.concierge import ConciergeAgent

            agent = ConciergeAgent()
            out = agent.run(ctx)
            payload = out.payload or {}
            text = (payload.get("reply") or "").strip() or agent.fallback_reply
            can_continue = bool(payload.get("canContinue", False))
            cited_chunk_ids = [c for c in (out.chunk_ids or []) if c]
        except Exception:  # noqa: BLE001
            logger.exception(
                "assistant.generation_failed request_id=%s thread_id=%s",
                request_id or "none",
                thread.id,
            )
            degraded = True
    else:
        text = envelope.replacement_body

    if degraded or not text:
        return None

    # PART 2/3 — low-risk public Concierge conversation is NON-BLOCKING.
    #
    # The old path first scanned the complete answer with the stream guard and replaced
    # any match with an indefinite "specialist is reviewing" notice. That meant a
    # truthful, RAG-grounded product explanation could dead-end because it happened to
    # contain a guarded phrase. `govern_text` now sanitizes claim-level-1 visitor chat
    # and returns it deliverable; higher-risk contexts still use their existing gates.
    try:
        from apps.agents.services.governance import govern_text

        decision = govern_text(text, claim_level=1, context="anonymous_review")
        governance_status = decision.get("status", "auto_approved")
        text = decision.get("text") or text
    except Exception:  # noqa: BLE001
        # Conversation delivery must not depend on a human-review queue. The model is
        # already constrained by the document-grounded Concierge prompt; on a local
        # governance failure keep the answer deliverable rather than strand the user.
        logger.exception("settle-time conversational governance unavailable; delivering")
        governance_status = "auto_approved"

    status = StreamingStatus.SETTLED

    # Internal names never reach a visitor; then the deterministic state/source/contract
    # policy applies regardless of whether the answer came from AI or fallback.
    from apps.conversations.services import response_policy, terminology

    text = terminology.normalise_outbound(text)
    text = response_policy.enforce(text, thread=thread)

    # v2.2 stated-mode-change requirement. A qualifying request does not silently flip
    # modes: the interface says exactly what changes and asks for explicit consent.
    mode_offer = getattr(thread, "_mode_change_offer", "") or ""
    if mode_offer and status == StreamingStatus.SETTLED and mode_offer not in text:
        text = f"{text.rstrip()}\n\n{mode_offer}" if text.strip() else mode_offer

    # My Review access is never placed in conversational text. A ready review is
    # surfaced through the one-time browser-bound reveal event and explicit UI action;
    # the URL itself remains credential-free (`/c`).
    reveal = getattr(thread, "_client_page_reveal", None)

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
        cited_chunk_ids=cited_chunk_ids,
        thread=thread,
        streaming_status=status,
        meta={"can_continue": can_continue},
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


# ── READY REVIEW HANDOFF ────────────────────────────────────────────────────
# My Review access is deliberately not carried in assistant prose.  The browser receives
# a separate realtime readiness/reveal signal, exchanges a short-lived browser-bound code
# through the Next.js BFF, and opens tokenless /c with an httpOnly session cookie.  This
# fallback copy therefore contains no URL or credential and is safe even if an older caller
# still invokes it.
WHAT_HAPPENS_NEXT = (
    "Your My Review reflects the current conversation state and is a decision-support "
    "artifact, not a measured result or contractual commitment. You can review it and "
    "continue the conversation if anything needs to be corrected or clarified."
)


def _append_client_page_link(text: str, url: str = "") -> str:
    """Legacy-safe handoff helper: never append a credential-bearing URL.

    Retained only for transport compatibility while older consumer call sites are removed.
    The secure UI owns review access; assistant text may announce readiness but must never
    carry the one-time exchange code or a durable bearer token.
    """
    body = (text or "").rstrip()
    notice = "Your My Review is ready. Use **View My Review** to open it securely."
    if notice in body:
        return body
    return f"{body}\n\n{notice}\n\n{WHAT_HAPPENS_NEXT}" if body else f"{notice}\n\n{WHAT_HAPPENS_NEXT}"
