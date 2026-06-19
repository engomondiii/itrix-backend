"""
Evaluation models.

``Evaluation`` tracks a paid evaluation through proposed → in_progress → delivered → won/lost,
with a list of KPI rows. Matches the dashboard's ``Evaluation`` type
(``{id, leadId, leadName, company, pkg, status, kpis[], createdAt, updatedAt}``) and
``EvaluationKPI`` (``{id, category, metric, target?, result?}``). KPIs are stored as JSON.
The package strings match the dashboard's ``EVALUATION_PACKAGES``.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class EvaluationStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    IN_PROGRESS = "in_progress", "In progress"
    DELIVERED = "delivered", "Delivered"
    WON = "won", "Won"
    LOST = "lost", "Lost"


class EvaluationPackage(models.TextChoices):
    COMPUTE = "ALPHA Compute Bottleneck Assessment", "ALPHA Compute Bottleneck Assessment"
    CORE = "ALPHA Core Runtime Fit Assessment", "ALPHA Core Runtime Fit Assessment"
    COMBINED = "Combined ALPHA Evaluation", "Combined ALPHA Evaluation"


class Evaluation(BaseModel):
    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.CASCADE, related_name="evaluations"
    )
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    pkg = models.CharField(
        max_length=64, choices=EvaluationPackage.choices, default=EvaluationPackage.COMPUTE
    )
    status = models.CharField(
        max_length=12, choices=EvaluationStatus.choices, default=EvaluationStatus.PROPOSED
    )
    kpis = models.JSONField(default=list, blank=True)
    # Captured when the evaluation is requested (dashboard's optional fields).
    scope = models.TextField(blank=True, default="")
    fee = models.CharField(max_length=120, blank=True, default="")
    timeline = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Evaluation"
        verbose_name_plural = "Evaluations"

    def __str__(self) -> str:
        return f"Evaluation({self.lead_name or self.lead_id}, {self.status})"
