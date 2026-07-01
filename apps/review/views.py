"""
Review views (PUBLIC — Surface 1, no auth).

    POST /api/v1/review/sessions/                  create a review session -> {id, ...}
    POST /api/v1/review/sessions/{id}/prompt/      submit prompt -> {sessionId, immediateResponse, nda_recommended}
    POST /api/v1/review/sessions/{id}/qualify/     submit answers -> authoritative score/tier/route + lead_id

The web proxies read:
  * session create  → ``id``  (api/review/submit creates the session if missing)
  * prompt          → returns ``{sessionId, immediateResponse}`` to the browser
  * qualify         → the full result; the client prefers this over its local estimate
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.review.models import ReviewSession
from apps.review.serializers import (
    PromptSubmitSerializer,
    QualifySubmitSerializer,
    ReviewSessionCreateSerializer,
    ReviewSessionSerializer,
)
from apps.review.services.prompt_handler import handle_prompt
from apps.review.services.qualification_processor import process_qualification
from apps.visitors.models import VisitorSession

logger = logging.getLogger("itrix")


class ReviewSessionCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request):
        serializer = ReviewSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        visitor_session = None
        vs_id = data.get("visitor_session_id")
        if vs_id:
            visitor_session = VisitorSession.objects.filter(pk=vs_id).first()
        # If the client sent a client_id but no session, link to the latest match.
        if visitor_session is None and data.get("client_id"):
            visitor_session = (
                VisitorSession.objects.filter(client_id=data["client_id"])
                .order_by("-created_at")
                .first()
            )

        session = ReviewSession.objects.create(
            visitor_session=visitor_session,
            client_id=data.get("client_id", "") or "",
            visitor_type=data.get("visitor_type") or "unknown",
        )
        logger.info("ReviewSession created: %s", session.id)
        return Response(
            ReviewSessionSerializer(session).data, status=status.HTTP_201_CREATED
        )


class PromptSubmitView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request, session_id):
        session = get_object_or_404(ReviewSession, pk=session_id)
        serializer = PromptSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = handle_prompt(
            session,
            prompt=data["prompt"],
            pressure_areas=data.get("pressure_areas", []),
            environment=data.get("environment", ""),
        )

        return Response(
            {
                "sessionId": str(session.id),
                "immediateResponse": result.immediate_response.to_dict(),
                "nda_recommended": result.nda_recommended,
            },
            status=status.HTTP_200_OK,
        )


class QualifyView(APIView):
    """On completion, score + route the answers and attach a (placeholder) lead id."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request, session_id):
        session = get_object_or_404(ReviewSession, pk=session_id)
        serializer = QualifySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = process_qualification(session, serializer.validated_data["answers"])
        return Response(result.to_dict(), status=status.HTTP_200_OK)


class ReviewChatView(APIView):
    """
    POST /api/v1/review/sessions/{id}/chat/  — PUBLIC.

    A review-chat turn with the Concierge. Persists the turn to the durable conversation
    and returns the governed reply synchronously (so the funnel works with realtime off).
    When governance holds the reply, ``underReview`` is true and ``reply`` is empty.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request, session_id):
        session = get_object_or_404(ReviewSession, pk=session_id)
        body = (request.data.get("message") or request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"error": {"detail": "message is required.", "code": "invalid"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.leads.models import Lead
        from apps.review.services.review_chat import handle_review_chat_turn

        lead = Lead.objects.filter(review_session=session).first()
        result = handle_review_chat_turn(
            review_session_id=str(session.id), lead=lead, body=body
        )
        return Response(
            {
                "conversationId": result.conversation_id,
                "reply": result.reply,
                "suggestNda": result.suggest_nda,
                "governanceStatus": result.governance_status,
                "underReview": result.under_review,
                "citedChunkIds": result.cited_chunk_ids,
            },
            status=status.HTTP_200_OK,
        )
