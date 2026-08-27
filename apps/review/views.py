"""
Review views (PUBLIC — Surface 1, no auth).

    POST /api/v1/review/sessions/                  create a review session -> {id, ...}
    POST /api/v1/review/sessions/{id}/prompt/      submit prompt -> {sessionId, immediateResponse, nda_recommended}
    POST /api/v1/review/sessions/{id}/qualify/     submit answers -> customer-safe generation acknowledgement

The web proxies read:
  * session create  → ``id``  (api/review/submit creates the session if missing)
  * prompt          → returns ``{sessionId, immediateResponse}`` to the browser
  * qualify         → a safe acknowledgement; scoring/routing stays internal
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
from apps.review.services import access_binding
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
            locale=data.get("locale") or "en",
            access_binding_hash=access_binding.digest(access_binding.raw_from_request(request)),
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
        if not access_binding.matches(session, request):
            return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
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
    """On completion, score/route internally and return only review readiness."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request, session_id):
        session = get_object_or_404(ReviewSession, pk=session_id)
        if not access_binding.matches(session, request):
            return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
        serializer = QualifySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = process_qualification(session, serializer.validated_data["answers"])
        return Response(result.to_public_dict(), status=status.HTTP_200_OK)


class ReviewResultStatusView(APIView):
    """Browser-bound readiness, access and retry endpoint for My Review.

    GET is a pure status read and never mints a credential.  POST accepts an explicit
    ``action``: ``open`` creates a short-lived one-time opaque exchange code only after
    the artifact is READY; ``retry`` restarts only a FAILED/missing generation. This
    avoids continuously rotating access codes while a page polls readiness.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def _session(self, request, session_id):
        session = ReviewSession.objects.filter(pk=session_id).first()
        if session is None or not access_binding.matches(session, request):
            return None
        return session

    @staticmethod
    def _lead(session):
        from apps.leads.models import Lead
        lead = Lead.objects.filter(review_session=session).first()
        if lead is None and session.placeholder_lead_id:
            lead = Lead.objects.filter(pk=session.placeholder_lead_id).first()
        return lead

    @staticmethod
    def _page(lead):
        from apps.result_page.models import ResultPage
        return ResultPage.objects.filter(lead=lead).first() if lead is not None else None

    @staticmethod
    def _status_payload(page):
        from apps.result_page.models import ResultPage
        if page is None:
            return {"generationStatus": "pending", "ready": False, "retryable": False}
        if page.generation_status == ResultPage.GenerationStatus.FAILED:
            return {"generationStatus": "failed", "ready": False, "retryable": True}
        if page.generation_status == ResultPage.GenerationStatus.READY:
            return {"generationStatus": "ready", "ready": True, "retryable": False}
        return {"generationStatus": "pending", "ready": False, "retryable": False}

    def get(self, request, session_id):
        session = self._session(request, session_id)
        if session is None:
            return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
        lead = self._lead(session)
        return Response(self._status_payload(self._page(lead)))

    def post(self, request, session_id):
        from apps.result_page.models import ResultPage
        from apps.review.services.qualification_processor import kick_off_result_page

        session = self._session(request, session_id)
        if session is None:
            return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
        lead = self._lead(session)
        if lead is None:
            return Response({"error": {"detail": "Review is not ready.", "code": "not_ready"}}, status=status.HTTP_409_CONFLICT)

        action = str(request.data.get("action") or "").strip().lower()
        page = self._page(lead)

        if action == "open":
            if page is None or page.generation_status != ResultPage.GenerationStatus.READY:
                return Response(self._status_payload(page), status=status.HTTP_409_CONFLICT)

            # The complete artifact exists. Advancing the numbered journey records that
            # the surface is available; authorization is still separately browser-bound.
            if getattr(lead, "journey_state", "") == "DIAGNOSED":
                try:
                    from apps.journey.services.advance import reveal_client_page
                    reveal_client_page(lead, meta={"source": "review_ready"})
                except Exception:
                    logger.exception("Could not advance ready review %s to CLIENT_PAGE", lead.id)

            raw_binding = access_binding.raw_from_request(request)
            if not raw_binding:
                return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
            from apps.result_page.services.client_access import issue_for_lead
            code = issue_for_lead(lead, visitor_session=raw_binding)
            return Response({"generationStatus": "ready", "ready": True, "accessCode": code})

        if action == "retry":
            if page and page.generation_status == ResultPage.GenerationStatus.READY:
                return Response({"generationStatus": "ready", "ready": True})
            if page and page.generation_status == ResultPage.GenerationStatus.PENDING:
                return Response({"generationStatus": "pending", "ready": False})
            kick_off_result_page(lead)
            return Response({"generationStatus": "pending", "ready": False}, status=status.HTTP_202_ACCEPTED)

        return Response(
            {"error": {"detail": "A valid review action is required.", "code": "invalid_action"}},
            status=status.HTTP_400_BAD_REQUEST,
        )


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
        if not access_binding.matches(session, request):
            return Response({"error": {"detail": "Review session unavailable.", "code": "not_found"}}, status=status.HTTP_404_NOT_FOUND)
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
                "reply": result.reply,
                "suggestNda": result.suggest_nda,
                "governanceStatus": result.governance_status,
                "underReview": result.under_review,
            },
            status=status.HTTP_200_OK,
        )
