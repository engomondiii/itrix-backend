"""
PoC models.

``PoC`` tracks a proof-of-concept through planning → active → completed/stalled/cancelled,
holding milestones, KPIs, and risks as JSON lists. Matches the dashboard's ``PoC`` type and
its nested ``PoCMilestone`` / ``PoCKPI`` / ``PoCRisk`` shapes.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class PoCStatus(models.TextChoices):
    PLANNING = "planning", "Planning"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    STALLED = "stalled", "Stalled"
    CANCELLED = "cancelled", "Cancelled"


class PoC(BaseModel):
    lead = models.ForeignKey("leads.Lead", on_delete=models.CASCADE, related_name="pocs")
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=12, choices=PoCStatus.choices, default=PoCStatus.PLANNING)
    milestones = models.JSONField(default=list, blank=True)  # [{id,label,status,dueAt?}]
    kpis = models.JSONField(default=list, blank=True)        # [{id,category,metric,baseline?,target?,result?}]
    risks = models.JSONField(default=list, blank=True)       # [{id,description,severity,mitigation?}]

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "PoC"
        verbose_name_plural = "PoCs"

    def __str__(self) -> str:
        return f"PoC({self.lead_name or self.lead_id}, {self.status})"
