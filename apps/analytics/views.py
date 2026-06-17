"""
Analytics view (JWT — Surface 2).

A single endpoint returns all seven analytics blocks, matching the dashboard's expectation
(``GET /analytics/?days=30``). The dashboard's per-widget proxies (overview, funnel,
bottlenecks, response-time) all call this one endpoint and extract the block they need:

    {
      "overview":            OverviewMetrics,
      "funnel":              FunnelStage[],
      "response_time":       ResponseTimeMetrics,
      "bottlenecks":         BottleneckPattern[],
      "industries":          IndustryBreakdown[],
      "route_distribution":  Record<ProductRoute, number>,
      "submission_trend":    {date,count}[]
    }
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services.bottleneck_pattern_analyzer import bottleneck_patterns
from apps.analytics.services.funnel_calculator import funnel
from apps.analytics.services.industry_breakdown import industry_breakdown
from apps.analytics.services.overview_aggregator import overview
from apps.analytics.services.route_distribution import route_distribution
from apps.analytics.services.sla_compliance_calculator import response_time_metrics
from apps.analytics.services.submission_trend import submission_trend
from apps.core.permissions import IsDashboardUser


class AnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        since = timezone.now() - timedelta(days=days)

        return Response(
            {
                "overview": overview(days=days),
                "funnel": funnel(since=since),
                "response_time": response_time_metrics(),
                "bottlenecks": bottleneck_patterns(since=since),
                "industries": industry_breakdown(since=since),
                "route_distribution": route_distribution(since=since),
                "submission_trend": submission_trend(days=days),
            }
        )
