"""
AI Engine models.

``GenerationLog`` records each result-generation request for auditability: which lead /
session it was for, whether the AI path was used (vs deterministic fallback), how many
knowledge chunks were retrieved, and any guard activity. This is operational telemetry,
not visitor-facing.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class GenerationLog(BaseModel):
    """An audit record for one AI result generation."""

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_logs",
    )
    review_session = models.ForeignKey(
        "review.ReviewSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_logs",
    )
    product_route = models.CharField(max_length=20, blank=True, default="")
    used_ai = models.BooleanField(default=False)
    chunk_count = models.PositiveIntegerField(default=0)
    prohibited_removed = models.JSONField(default=list, blank=True)
    quant_hedged = models.JSONField(default=list, blank=True)
    ok = models.BooleanField(default=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Generation log"
        verbose_name_plural = "Generation logs"

    def __str__(self) -> str:
        return f"GenerationLog(lead={self.lead_id}, ai={self.used_ai}, ok={self.ok})"
