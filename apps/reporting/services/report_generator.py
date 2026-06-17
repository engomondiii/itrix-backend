"""
Report generator.

Generates (or regenerates) a monthly report by pulling the analytics blocks and turning them
into narrative sections. Idempotent per month (update_or_create). The analytics window is the
month length, approximated as 30 days ending now — good enough for the MVP rollup.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.reporting.models import MonthlyReport
from apps.reporting.services.report_sections import build_sections

logger = logging.getLogger("itrix")


def _gather_analytics(days: int = 30) -> dict:
    from datetime import timedelta

    from apps.analytics.services.bottleneck_pattern_analyzer import bottleneck_patterns
    from apps.analytics.services.funnel_calculator import funnel
    from apps.analytics.services.industry_breakdown import industry_breakdown
    from apps.analytics.services.overview_aggregator import overview
    from apps.analytics.services.route_distribution import route_distribution
    from apps.analytics.services.sla_compliance_calculator import response_time_metrics

    since = timezone.now() - timedelta(days=days)
    return {
        "overview": overview(days=days),
        "funnel": funnel(since=since),
        "response_time": response_time_metrics(),
        "bottlenecks": bottleneck_patterns(since=since),
        "industries": industry_breakdown(since=since),
        "route_distribution": route_distribution(since=since),
    }


def generate_monthly_report(*, month: str | None = None) -> MonthlyReport:
    """Generate the report for ``month`` (YYYY-MM); defaults to the current month."""
    month = month or timezone.now().strftime("%Y-%m")
    analytics = _gather_analytics()
    sections = build_sections(analytics, month=month)

    report, _created = MonthlyReport.objects.update_or_create(
        month=month, defaults={"sections": sections}
    )
    logger.info("Monthly report generated for %s (%d sections)", month, len(sections))
    return report
