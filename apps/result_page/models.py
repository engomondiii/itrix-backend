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
    # Canonical six-part STR-03 payload. Kept separately from the legacy one-paragraph
    # mirror so older internal readers can migrate without forcing raw JSON into prose.
    problem_mirror_structured = models.JSONField(default=dict, blank=True)
    # Public-safe personalization summary (audience/focus only; never hidden persona ids/scores).
    persona_context = models.JSONField(default=dict, blank=True)
    diagnosis = models.JSONField(default=list, blank=True)  # [{pressure,observation,...}]
    alpha_fit_summary = models.TextField(blank=True, default="")
    kpi_preview = models.JSONField(default=list, blank=True)  # [{label,metric}]
    proof_preview = models.JSONField(default=list, blank=True)  # [{title,disclosure,reference?}]
    recommended_next_step = models.TextField(blank=True, default="")

    class GenerationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    used_ai = models.BooleanField(default=False)
    generation_status = models.CharField(
        max_length=16, choices=GenerationStatus.choices, default=GenerationStatus.PENDING, db_index=True
    )
    # Internal-only diagnostic. Never serialized to the visitor/client plane.
    generation_error = models.TextField(blank=True, default="")
    artifact_family = models.CharField(max_length=48, blank=True, default="my_review")
    artifact_version = models.PositiveIntegerField(default=1)
    locale = models.CharField(max_length=12, blank=True, default="en")
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at"]
        verbose_name = "Result page"
        verbose_name_plural = "Result pages"

    def __str__(self) -> str:
        return f"ResultPage(lead={self.lead_id}, tier={self.tier})"


class ClientPageAccessGrant(BaseModel):
    """One-time opaque exchange code for a personalized review."""

    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.CASCADE, related_name="client_page_access_grants"
    )
    code_hash = models.CharField(max_length=64, unique=True, db_index=True)
    # Hash only; never persist the anonymous session cookie itself on this access row.
    visitor_session_hash = models.CharField(max_length=64, blank=True, default="")
    client_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["lead", "expires_at"])]


class ClientPageAccessSession(BaseModel):
    """Opaque server-side review session; raw token belongs only in an httpOnly cookie."""

    grant = models.OneToOneField(
        ClientPageAccessGrant, on_delete=models.CASCADE, related_name="access_session"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
