"""
v6.0 Phase 3 analytics endpoints — TEAM PLANE ONLY.

    analytics/customers/     health board
    analytics/support/       queue depth, SLA compliance, ageing
    analytics/outcomes/      outcome status distribution
    analytics/conversations/ thread depth, turns-to-artifact, loop productivity
    analytics/attachments/   volume, type mix, extraction, quarantine
    analytics/streaming/     envelope downgrades, guard halts, settle replacements

EVERY ONE IS INTERNAL-ONLY. The aggregates here read fields on the §10.5 list —
``customer_health``, ``coverage_map``, ``stop_reason``, ``attachment_risk_flags``,
``stream_guard_hits``. There is no client-plane mount for any of them and there must
never be one.
"""

from __future__ import annotations

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser

logger = logging.getLogger("itrix")


class _TeamAnalyticsView(APIView):
    """Shared base. Team-JWT only — there is deliberately no AllowAny path in here."""

    permission_classes = [IsAuthenticated, IsDashboardUser]


class CustomerHealthAnalyticsView(_TeamAnalyticsView):
    """GET analytics/customers/ — the health board."""

    def get(self, request):
        from apps.analytics.services import customer_health

        return Response({**customer_health.summary(), "board": customer_health.board()})


class SupportLoadAnalyticsView(_TeamAnalyticsView):
    """GET analytics/support/ — queue depth, SLA compliance, ageing."""

    def get(self, request):
        from apps.analytics.services import support_load

        return Response(support_load.summary())


class OutcomeProgressAnalyticsView(_TeamAnalyticsView):
    """GET analytics/outcomes/ — outcome status distribution."""

    def get(self, request):
        from apps.analytics.services import outcome_progress

        return Response(outcome_progress.summary())


class ConversationAnalyticsView(_TeamAnalyticsView):
    """GET analytics/conversations/ — thread depth, loop productivity, abandonment."""

    def get(self, request):
        from apps.analytics.services import conversation_metrics

        return Response(conversation_metrics.summary())


class AttachmentAnalyticsView(_TeamAnalyticsView):
    """GET analytics/attachments/ — volume, type mix, extraction, quarantine."""

    def get(self, request):
        from apps.analytics.services import attachment_metrics

        return Response(attachment_metrics.summary())


class StreamingAnalyticsView(_TeamAnalyticsView):
    """
    GET analytics/streaming/ — governance telemetry.

    Includes the DRIFT SIGNAL. §6.4: a rising guard-hit rate is retrieval or prompt
    drift, not noise — so the endpoint reports the trend, not just the total.
    """

    def get(self, request):
        from apps.analytics.services import stream_metrics

        return Response({**stream_metrics.summary(), "recent": stream_metrics.recent_hits()})
