"""
Review models.

``ReviewSession`` is the record of one visitor going through the Compute Bottleneck
Review: the prompt and pressure areas they submitted, NDA detection flags, the
qualification answers, and the computed score / tier / routes. It links back to the
``VisitorSession`` so a visitor's room visits and review are one thread.

In Phase 1 the ``placeholder_lead_id`` carries the result step (it equals the review
session id). In Phase 2 the real Lead is created and a proper FK/id replaces it; the
field stays for backward-compatible references and audit.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class ReviewSession(BaseModel):
    class Status(models.TextChoices):
        STARTED = "STARTED", "Started"
        PROMPTED = "PROMPTED", "Prompted"
        QUALIFIED = "QUALIFIED", "Qualified"

    visitor_session = models.ForeignKey(
        "visitors.VisitorSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_sessions",
    )
    client_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    visitor_type = models.CharField(max_length=32, blank=True, default="unknown")

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.STARTED, db_index=True
    )

    # ── Prompt step ──────────────────────────────────────────────────────────
    prompt = models.TextField(blank=True, default="")
    pressure_areas = models.JSONField(default=list, blank=True)
    environment = models.CharField(max_length=64, blank=True, default="")

    # NDA detection (set by nda_detector via prompt_handler)
    nda_recommended = models.BooleanField(default=False)
    nda_signals = models.JSONField(default=list, blank=True)

    # ── Qualification step ───────────────────────────────────────────────────
    answers = models.JSONField(default=dict, blank=True)
    score_breakdown = models.JSONField(default=dict, blank=True)
    score_total = models.PositiveSmallIntegerField(null=True, blank=True)
    tier = models.PositiveSmallIntegerField(null=True, blank=True)
    product_route = models.CharField(max_length=20, blank=True, default="")
    license_pathway = models.CharField(max_length=20, blank=True, default="")

    # Placeholder lead reference (Phase 1). Phase 2 replaces with the real Lead id.
    placeholder_lead_id = models.UUIDField(null=True, blank=True)

    # ── v6.0 Phase 3: why the question loop stopped ──────────────────────────
    # Persisted so the cockpit can audit an unproductive loop (§5.3). A spike in
    # ``question_budget_exhausted`` means we run out of budget before understanding;
    # a spike in ``visitor_declined`` means the questions are unwelcome. Without the
    # column those two look identical.
    #
    # INTERNAL-ONLY (§10.5) — never on a client-plane payload.
    stop_reason = models.CharField(max_length=40, blank=True, default="", db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Review session"
        verbose_name_plural = "Review sessions"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["tier"]),
        ]

    def __str__(self) -> str:
        return f"ReviewSession({self.id}, {self.status})"

    @property
    def is_qualified(self) -> bool:
        return self.status == self.Status.QUALIFIED
