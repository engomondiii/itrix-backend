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

── v7.1 PHASE 1: THESE ARE THE AGGREGATES, AND THEY LIVE ONLY HERE ─────────
v6.0 also mounted four of them at ``cockpit/``, which made ``cockpit/threads/`` return
thread METRICS while the dashboard asked it for a thread LIST. Those second mounts are
gone (see api/v1/cockpit_urls.py); the row-level resources own the ``cockpit/`` names now.

    AGGREGATES under analytics/         distributions, counts, trends   <- this file
    ROW-LEVEL RESOURCES under cockpit/   individual threads, customers, halts

One further change: ``analytics/streaming/`` now role-filters ``matchedText``. It was
returning the platform's own prohibited wording to any team member, VIEWER included.
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
        from apps.cockpit.permissions import may_see_matched_text

        # v7.1 Phase 1. `recent_hits` used to return `matchedText` to any team member,
        # including VIEWER. The role check happens here, and the service defaults to the
        # restrictive answer so an un-updated caller fails closed.
        allowed = may_see_matched_text(request.user)
        return Response(
            {
                **stream_metrics.summary(),
                "recent": stream_metrics.recent_hits(may_see_matched_text=allowed),
                # Stated in the payload so the dashboard labels the column honestly rather
                # than inferring from a missing key.
                "matchedTextVisible": allowed,
            }
        )
