"""
Result Page views.

    GET  result-page/{lead_id}/   PUBLIC — the web result page fetches this after generate.
    POST result-page/generate/    JWT    — internal: (re)generate a result for a lead.

The GET resolves a lead by id (accepting the pre-Phase-2 placeholder id, which equals the
review-session id) and returns the stored result; if none exists yet it generates one on the
fly so the page is never empty. The POST lets internal tools force a regeneration.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead
from apps.result_page.models import ResultPage
from apps.result_page.serializers import ResultPageSerializer
from apps.result_page.services.result_generator import ResultGenerator
from apps.review.models import ReviewSession

logger = logging.getLogger("itrix")


def _resolve_lead(lead_ref: str) -> Lead | None:
    """Resolve a lead by its id, or by a review-session id (placeholder lead id)."""
    lead = Lead.objects.filter(pk=lead_ref).first()
    if lead:
        return lead
    session = ReviewSession.objects.filter(pk=lead_ref).first()
    if session:
        return Lead.objects.filter(review_session=session).first()
    return None


class ResultPageDetailView(APIView):
    """PUBLIC — return the stored result page for a lead (generating if needed)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, lead_id: str):
        lead = _resolve_lead(lead_id)
        if lead is None:
            return Response(
                {"error": {"detail": "Result not found.", "code": "not_found"}},
                status=status.HTTP_404_NOT_FOUND,
            )

        result_obj = ResultPage.objects.filter(lead=lead).first()
        if result_obj is None:
            # Generate on demand so the page is never empty.
            result_obj, _report = ResultGenerator().generate_for_lead(lead)

        return Response(ResultPageSerializer(result_obj).data)


class ResultPageGenerateView(APIView):
    """JWT — force (re)generation of a lead's result page."""

    permission_classes = [IsAuthenticated, IsDashboardUser, IsNotViewer]

    def post(self, request):
        lead_ref = request.data.get("lead_id")
        if not lead_ref:
            return Response(
                {"error": {"detail": "lead_id is required.", "code": "invalid"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lead = _resolve_lead(lead_ref)
        if lead is None:
            return Response(
                {"error": {"detail": "Lead not found.", "code": "not_found"}},
                status=status.HTTP_404_NOT_FOUND,
            )
        result_obj, _report = ResultGenerator().generate_for_lead(lead)
        return Response(ResultPageSerializer(result_obj).data, status=status.HTTP_201_CREATED)


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2 — the customized CLIENT PAGE (behind the client_page capability token)
# ═════════════════════════════════════════════════════════════════════════════
class ResultPageClientView(APIView):
    """
    GET client-page/{token}/ — PUBLIC (token-gated).

    Verifies the client_page capability token, asserts the journey permits the client
    page, and returns the customized page (result sections + embedded Pitch room). Data
    is released only when (token valid) AND (journey permits) AND (disclosure allows).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, token: str):
        from apps.journey.models import JourneyState
        from apps.journey.services import capability_token as ct

        try:
            payload = ct.verify(token, expected_typ=ct.TOKEN_CLIENT_PAGE)
        except ct.CapabilityTokenError as exc:
            return Response({"detail": f"Invalid token: {exc}"}, status=status.HTTP_404_NOT_FOUND)

        lead = Lead.objects.filter(id=payload.sub).first()
        if lead is None:
            return Response({"detail": "Unknown subject."}, status=status.HTTP_404_NOT_FOUND)

        # Journey must have reached (or passed) CLIENT_PAGE for the page to be reachable.
        # Expressed as a NUMBER rather than a set of members so adding a state to the
        # ladder never silently makes the page unreachable from it. DORMANT is off-ladder
        # but has seen the page, so it is admitted explicitly.
        from apps.journey.models import journey_number, normalize_state

        state = normalize_state(lead.journey_state)
        number = journey_number(state)
        reached = state == JourneyState.DORMANT.value or (number is not None and number >= 4)
        if not reached:
            return Response({"detail": "Not yet available."}, status=status.HTTP_404_NOT_FOUND)

        data = ResultGenerator().build_client_page(lead, context="public")
        return Response(data, status=status.HTTP_200_OK)


class ResultPageClientChatView(APIView):
    """
    POST client-page/{token}/chat/ — PUBLIC (token-gated).

    Chat on the customized client page. Verifies the client_page token, resolves the
    lead's client-page conversation, and returns the governed Concierge reply. Shares the
    review-chat code path (persist + route + fan out).
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "review_submit"

    def post(self, request, token: str):
        from apps.journey.services import capability_token as ct

        try:
            payload = ct.verify(token, expected_typ=ct.TOKEN_CLIENT_PAGE)
        except ct.CapabilityTokenError as exc:
            return Response({"detail": f"Invalid token: {exc}"}, status=status.HTTP_404_NOT_FOUND)

        lead = Lead.objects.filter(id=payload.sub).first()
        if lead is None:
            return Response({"detail": "Unknown subject."}, status=status.HTTP_404_NOT_FOUND)

        body = (request.data.get("message") or request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"error": {"detail": "message is required.", "code": "invalid"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Route through the client-page conversation → Concierge (governed).
        from apps.agents.services.context import AgentContext, PLANE_PUBLIC
        from apps.agents.services.runtime import run_concierge
        from apps.conversations.services import fan_out, ingest
        from apps.conversations.services.history import get_or_create_client_page_conversation

        conv = get_or_create_client_page_conversation(lead)
        inbound = ingest.ingest_inbound(conv, sender_kind="visitor", body=body)
        fan_out.broadcast_message(inbound)

        session = getattr(lead, "review_session", None)
        out = run_concierge(
            AgentContext(
                lead_id=str(lead.id),
                prompt=getattr(session, "prompt", "") or body,
                pressures=list(getattr(session, "pressure_areas", []) or []),
                product_route=lead.product_route,
                license_pathway=lead.commercial_path if lead.commercial_path != "none" else None,
                tier=lead.tier,
                plane=PLANE_PUBLIC,
                context_label="client_page",
                extra={"message": body},
            )
        )
        payload_out = out.payload or {}
        reply_msg = ingest.ingest_agent_message(
            conv,
            agent_key="concierge",
            body=payload_out.get("reply", ""),
            governance_status=out.governance_status,
            claim_level=out.claim_level,
            cited_chunk_ids=out.chunk_ids,
        )
        fan_out.broadcast_message(reply_msg)

        return Response(
            {
                "conversationId": str(conv.id),
                "reply": payload_out.get("reply", "") if reply_msg.is_deliverable else "",
                "suggestNda": bool(payload_out.get("suggestNda", False)),
                "governanceStatus": out.governance_status,
                "underReview": not reply_msg.is_deliverable,
                "citedChunkIds": out.chunk_ids,
            },
            status=status.HTTP_200_OK,
        )
