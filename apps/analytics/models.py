"""
Analytics models.

Analytics are computed on demand from the live data (leads, follow-ups, etc.), so no model
is strictly required for the dashboard. ``MetricSnapshot`` is an optional periodic capture of
the overview block, written by the scheduled Celery beat job, so reporting can show trends
over time and the dashboard can render history cheaply. It is never required for the live
``/analytics/`` endpoint, which always aggregates fresh.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class MetricSnapshot(BaseModel):
    """A point-in-time capture of headline metrics."""

    captured_for = models.DateField(db_index=True, help_text="The day this snapshot summarises.")
    new_leads = models.PositiveIntegerField(default=0)
    tier1_count = models.PositiveIntegerField(default=0)
    tier2_count = models.PositiveIntegerField(default=0)
    overdue_follow_ups = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True, help_text="Full overview block JSON.")

    class Meta:
        ordering = ["-captured_for"]
        verbose_name = "Metric snapshot"
        verbose_name_plural = "Metric snapshots"
        constraints = [
            models.UniqueConstraint(fields=["captured_for"], name="unique_snapshot_per_day")
        ]

    def __str__(self) -> str:
        return f"MetricSnapshot({self.captured_for}: {self.new_leads} new)"
