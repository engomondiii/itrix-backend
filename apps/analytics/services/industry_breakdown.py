"""
Industry breakdown.

Counts leads by industry (the human-readable industry stored on the lead), descending by
count — matches ``IndustryBreakdown[] = {industry, count}``.
"""

from __future__ import annotations

from django.db.models import Count

from apps.leads.models import Lead


def industry_breakdown(*, since=None, limit: int = 12) -> list[dict]:
    qs = Lead.objects.exclude(industry="")
    if since:
        qs = qs.filter(submitted_at__gte=since)
    rows = (
        qs.values("industry")
        .annotate(count=Count("id"))
        .order_by("-count")[:limit]
    )
    return [{"industry": r["industry"], "count": r["count"]} for r in rows]
