"""
AI Engine views.

``GenerateResultView`` (PUBLIC — Surface 1) backs ``ai/generate-result/``: the web result
proxy POSTs ``{lead_id, session_id}`` here, then GETs ``result-page/{leadId}/``. This view
resolves the lead (by ``lead_id`` or via the review ``session_id``), generates+persists the
result page (deterministic, enriched by RAG when the engine is on), logs the generation,
and returns the result payload so the client has it immediately.

It always returns a usable result (200) when a lead/session can be resolved, so the public
funnel completes with or without the AI engine. If nothing resolves, it returns 404 and the
client uses its local fallback.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_engine.models import GenerationLog
from apps.ai_engine.serializers import GenerateResultRequestSerializer
from apps.leads.models import Lead
from apps.review.models import ReviewSession

logger = logging.getLogger("itrix")


class GenerateResultView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request):
        serializer = GenerateResultRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lead = self._resolve_lead(data.get("lead_id"), data.get("session_id"))
        if lead is None:
            return Response(
                {"error": {"detail": "No lead or session found to generate a result.", "code": "not_found"}},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Generate + persist via the result_page service (imported here to avoid a
        # module-load cycle between ai_engine and result_page).
        from apps.result_page.services.result_generator import ResultGenerator

        try:
            result_obj, report = ResultGenerator().generate_for_lead(lead)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Result generation failed for lead %s", lead.id)
            GenerationLog.objects.create(
                lead=lead,
                review_session=lead.review_session,
                product_route=lead.product_route,
                used_ai=False,
                ok=False,
                error=str(exc)[:2000],
            )
            return Response(
                {"error": {"detail": "Result generation failed.", "code": "generation_failed"}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        GenerationLog.objects.create(
            lead=lead,
            review_session=lead.review_session,
            product_route=lead.product_route,
            used_ai=report.get("used_ai", False),
            chunk_count=report.get("chunk_count", 0),
            prohibited_removed=report.get("prohibited_removed", []),
            quant_hedged=report.get("quant_hedged", []),
            ok=True,
        )

        from apps.result_page.serializers import ResultPageSerializer

        return Response(ResultPageSerializer(result_obj).data, status=status.HTTP_200_OK)

    @staticmethod
    def _resolve_lead(lead_id: str | None, session_id: str | None) -> Lead | None:
        if lead_id:
            lead = Lead.objects.filter(pk=lead_id).first()
            if lead:
                return lead
            # The web "placeholder" lead_id equals the review-session id pre-Phase-2.
            session = ReviewSession.objects.filter(pk=lead_id).first()
            if session:
                return Lead.objects.filter(review_session=session).first()
        if session_id:
            session = ReviewSession.objects.filter(pk=session_id).first()
            if session:
                return Lead.objects.filter(review_session=session).first()
        return None
