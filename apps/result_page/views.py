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
