"""
Overview aggregator.

Builds the headline ``OverviewMetrics`` block: new-lead count, Tier 1 / Tier 2 counts,
overdue follow-ups, tier distribution, route distribution, and the weekly submission series.
Field names match the dashboard's ``OverviewMetrics`` type exactly (camelCase).
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.analytics.services.route_distribution import route_distribution
from apps.analytics.services.submission_trend import submission_trend
from apps.leads.models import Lead


def _overdue_count() -> int:
    try:
        from apps.follow_up.services.sla_breach_checker import find_overdue

        return find_overdue().count()
    except Exception:  # noqa: BLE001
        return 0


def overview(*, days: int = 30) -> dict:
    now = timezone.now()
    since = now - timedelta(days=days)

    window = Lead.objects.filter(submitted_at__gte=since)
    tier_dist = {1: 0, 2: 0, 3: 0, 4: 0}
    for t in window.values_list("tier", flat=True):
        tier_dist[t] = tier_dist.get(t, 0) + 1

    return {
        "newLeads": window.count(),
        "tier1Count": tier_dist.get(1, 0),
        "tier2Count": tier_dist.get(2, 0),
        "overdueFollowUps": _overdue_count(),
        "tierDistribution": tier_dist,
        "routeDistribution": route_distribution(since=since),
        "weeklySubmissions": submission_trend(days=min(days, 14)),
    }
