"""
Result Page model.

``ResultPage`` persists the generated, personalized result for a lead so that the web's
two-step flow works: POST ``ai/generate-result/`` creates/refreshes this record, then GET
``result-page/{leadId}/`` returns it. Storing it (rather than regenerating per request)
keeps the result stable for the visitor and cheap to re-fetch, and gives us a record of
exactly what each visitor was shown.

The stored fields map 1:1 onto the web ``ResultPage`` type; the serializer emits them in
the camelCase the frontend expects.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class ResultPage(BaseModel):
    """A generated result page bound to a lead (one-to-one)."""

    lead = models.OneToOneField(
        "leads.Lead", on_delete=models.CASCADE, related_name="result_page"
    )

    tier = models.PositiveSmallIntegerField(default=4)
    score_breakdown = models.JSONField(default=dict, blank=True)
    product_route = models.CharField(max_length=20, default="general")  # display string
    license_pathway = models.CharField(max_length=40, blank=True, default="")  # display or ""
    primary_technologies = models.JSONField(default=list, blank=True)  # ["axiom","cre",...]

    problem_mirror = models.TextField(blank=True, default="")
    diagnosis = models.JSONField(default=list, blank=True)  # [{pressure,observation,...}]
    alpha_fit_summary = models.TextField(blank=True, default="")
    kpi_preview = models.JSONField(default=list, blank=True)  # [{label,metric}]
    proof_preview = models.JSONField(default=list, blank=True)  # [{title,disclosure,reference?}]
    recommended_next_step = models.TextField(blank=True, default="")

    used_ai = models.BooleanField(default=False)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at"]
        verbose_name = "Result page"
        verbose_name_plural = "Result pages"

    def __str__(self) -> str:
        return f"ResultPage(lead={self.lead_id}, tier={self.tier})"
