"""
Reporting models.

``MonthlyReport`` is a generated, point-in-time narrative report for a month, composed of
sections. Matches the dashboard's ``MonthlyReport`` (``{id, month, generatedAt, sections[]}``)
and ``ReportSection`` (``{id, title, body}``). Sections are stored as JSON since they're a
generated artifact, not separately editable records.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class MonthlyReport(BaseModel):
    month = models.CharField(max_length=7, db_index=True, help_text="YYYY-MM")
    sections = models.JSONField(default=list, blank=True)  # [{id,title,body}]
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        verbose_name = "Monthly report"
        verbose_name_plural = "Monthly reports"

    def __str__(self) -> str:
        return f"MonthlyReport({self.month})"
