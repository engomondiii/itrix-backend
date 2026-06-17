"""
Celery tasks for analytics + reporting.

``snapshot_metrics`` captures today's overview block (beat-scheduled). ``generate_report``
rolls up a monthly report. Eager when ENABLE_CELERY=False.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="analytics.snapshot_metrics")
def snapshot_metrics_task() -> dict:
    from django.utils import timezone

    from apps.analytics.models import MetricSnapshot
    from apps.analytics.services.overview_aggregator import overview

    block = overview(days=1)
    today = timezone.now().date()
    snap, _ = MetricSnapshot.objects.update_or_create(
        captured_for=today,
        defaults={
            "new_leads": block["newLeads"],
            "tier1_count": block["tier1Count"],
            "tier2_count": block["tier2Count"],
            "overdue_follow_ups": block["overdueFollowUps"],
            "payload": block,
        },
    )
    return {"ok": True, "snapshot_id": str(snap.id), "for": str(today)}


@shared_task(name="analytics.generate_report")
def generate_report_task(month: str | None = None) -> dict:
    from apps.reporting.services.report_generator import generate_monthly_report

    report = generate_monthly_report(month=month)
    return {"ok": True, "report_id": str(report.id), "month": report.month}
