"""
Submission trend.

Daily lead-submission counts over the window, as ``[{date: 'YYYY-MM-DD', count: n}]`` —
matches ``OverviewMetrics.weeklySubmissions``. Days with no submissions are included as 0 so
the chart is continuous.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.leads.models import Lead


def submission_trend(*, days: int = 30) -> list[dict]:
    now = timezone.now()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    counts: dict[str, int] = {}
    for lead in Lead.objects.filter(submitted_at__gte=start).only("submitted_at"):
        key = timezone.localtime(lead.submitted_at).date().isoformat()
        counts[key] = counts.get(key, 0) + 1

    series = []
    for i in range(days):
        day = (start + timedelta(days=i)).date().isoformat()
        series.append({"date": day, "count": counts.get(day, 0)})
    return series
