"""
Lead models — the core CRM record.

``Lead`` is created when a visitor completes the review (qualify). It stores the
qualification answers, the authoritative score breakdown + tier, the routed product /
license pathway, the AI-generated bottleneck summary and next step, ownership, status,
special rights, and SLA fields.

Enum design (Backend v3) and the dashboard contract:

* **Status (12)** — the dashboard renders/filters by display-label strings
  ("New", "Contacted", …), so we store those labels. v3 expands the dashboard's 8 to
  12 by adding intermediate operational states; the 8 dashboard values are a subset, so
  the dashboard keeps working and the extra states are available to the backend/pipeline.
* **SpecialRights (7)** — dashboard's 5 + 2 (v3). Stored as display labels.
* **LeadActivity types (11)** — dashboard's 10 (incl. ``meeting``) + ``paid_eval`` companion.
* **product_route / commercial_path** — stored as canonical codes
  (``alpha_compute`` / ``non_exclusive`` …) and serialized to the dashboard's display
  strings ("ALPHA Compute" / "Non-Exclusive") by the serializer.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class LeadStatus(models.TextChoices):
    """12 lifecycle statuses. The first 8 match the dashboard's pipeline columns."""

    NEW = "New", "New"
    CONTACTED = "Contacted", "Contacted"
    MEETING_BOOKED = "Meeting Booked", "Meeting Booked"
    NDA = "NDA", "NDA"
    EVALUATION = "Evaluation", "Evaluation"
    POC = "PoC", "PoC"
    LICENSED = "Licensed", "Licensed"
    CLOSED = "Closed", "Closed"
    # ── v3 additional operational states ─────────────────────────────────────
    QUALIFYING = "Qualifying", "Qualifying"
    NURTURE = "Nurture", "Nurture"
    NEGOTIATION = "Negotiation", "Negotiation"
    LOST = "Lost", "Lost"


class SpecialRights(models.TextChoices):
    """7 reserved-rights types. The first 5 match the dashboard."""

    NONE = "None", "None"
    FIELD = "Field", "Field"
    TERRITORY = "Territory", "Territory"
    PRODUCT_CATEGORY = "Product-Category", "Product-Category"
    ACQUISITION = "Acquisition", "Acquisition"
    # ── v3 additional ────────────────────────────────────────────────────────
    EXCLUSIVE_GLOBAL = "Exclusive-Global", "Exclusive-Global"
    TIME_LIMITED = "Time-Limited", "Time-Limited"


class ProductRouteCode(models.TextChoices):
    ALPHA_COMPUTE = "alpha_compute", "ALPHA Compute"
    ALPHA_CORE = "alpha_core", "ALPHA Core"
    BOTH = "both", "Both"
    GENERAL = "general", "General"


class CommercialPathCode(models.TextChoices):
    NON_EXCLUSIVE = "non_exclusive", "Non-Exclusive"
    EXCLUSIVE = "exclusive", "Exclusive"
    STRATEGIC = "strategic", "Strategic"
    NONE = "none", "None"


# Display-label maps used by serializers (code -> dashboard display string).
PRODUCT_ROUTE_DISPLAY = {
    "alpha_compute": "ALPHA Compute",
    "alpha_core": "ALPHA Core",
    "both": "Both",
    "general": "ALPHA Compute",  # general surfaces as Compute-leaning in the dashboard
}
COMMERCIAL_PATH_DISPLAY = {
    "non_exclusive": "Non-Exclusive",
    "exclusive": "Exclusive",
    "strategic": "Strategic",
    "none": "Non-Exclusive",
    "": "Non-Exclusive",
}

TERMINAL_STATUSES = {LeadStatus.LICENSED, LeadStatus.CLOSED, LeadStatus.LOST}


class Lead(BaseModel):
    """A qualified lead in the CRM."""

    # ── Link back to the originating review/visitor ──────────────────────────
    review_session = models.ForeignKey(
        "review.ReviewSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    client_id = models.CharField(max_length=128, blank=True, default="", db_index=True)

    # ── Contact / identity (filled progressively; email may arrive via capture) ─
    visitor_name = models.CharField(max_length=200, blank=True, default="")
    company = models.CharField(max_length=200, blank=True, default="")
    email = models.EmailField(blank=True, default="", db_index=True)
    industry = models.CharField(max_length=120, blank=True, default="")
    role = models.CharField(max_length=120, blank=True, default="")

    # ── Routing ──────────────────────────────────────────────────────────────
    product_route = models.CharField(
        max_length=20, choices=ProductRouteCode.choices, default=ProductRouteCode.GENERAL
    )
    commercial_path = models.CharField(
        max_length=20, choices=CommercialPathCode.choices, default=CommercialPathCode.NONE
    )
    special_rights = models.CharField(
        max_length=40, choices=SpecialRights.choices, default=SpecialRights.NONE
    )

    # ── Problem framing ──────────────────────────────────────────────────────
    compute_bottleneck = models.TextField(
        blank=True, default="", help_text="AI-generated summary of the bottleneck."
    )
    primary_pain = models.CharField(max_length=120, blank=True, default="")
    workload_type = models.CharField(max_length=120, blank=True, default="")
    current_stack = models.JSONField(default=list, blank=True)
    commercial_intent = models.CharField(max_length=120, blank=True, default="")
    timeline = models.CharField(max_length=120, blank=True, default="")

    # ── Scoring ──────────────────────────────────────────────────────────────
    score = models.PositiveSmallIntegerField(default=0)
    tier = models.PositiveSmallIntegerField(default=4)
    score_breakdown = models.JSONField(default=dict, blank=True)
    recommended_next_step = models.TextField(blank=True, default="")
    human_handoff_trigger = models.BooleanField(default=False)

    # ── Qualification answers (Q1–Q9 raw) ────────────────────────────────────
    qualification = models.JSONField(default=dict, blank=True)

    # ── Workflow / ownership ─────────────────────────────────────────────────
    status = models.CharField(
        max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_leads",
    )

    # ── Engagement signals ───────────────────────────────────────────────────
    cta_clicked = models.CharField(max_length=120, blank=True, default="")
    documents_viewed = models.PositiveIntegerField(default=0)

    # ── SLA fields ───────────────────────────────────────────────────────────
    sla_response_due_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    escalated = models.BooleanField(default=False)
    escalated_at = models.DateTimeField(null=True, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        indexes = [
            models.Index(fields=["tier", "status"]),
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self) -> str:
        who = self.company or self.visitor_name or self.email or "lead"
        return f"Lead({who}, T{self.tier}, {self.status})"

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    @property
    def product_route_display(self) -> str:
        return PRODUCT_ROUTE_DISPLAY.get(self.product_route, "ALPHA Compute")

    @property
    def commercial_path_display(self) -> str:
        return COMMERCIAL_PATH_DISPLAY.get(self.commercial_path, "Non-Exclusive")


class LeadNote(BaseModel):
    """An internal note attached to a lead."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_notes",
    )
    author_name = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LeadNote({self.lead_id})"


class LeadMeeting(BaseModel):
    """A meeting scheduled with a lead (captured by the Book meeting flow)."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="meetings")
    scheduled_at = models.DateTimeField()
    duration_mins = models.PositiveIntegerField(default=30)
    attendee = models.CharField(max_length=200, blank=True, default="")
    location = models.CharField(max_length=500, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booked_meetings",
    )
    booked_by_name = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-scheduled_at"]

    def __str__(self) -> str:
        return f"LeadMeeting({self.lead_id}, {self.scheduled_at})"


class LeadActivity(BaseModel):
    """A timeline entry for a lead. 11 activity types (Backend v3)."""

    class ActivityType(models.TextChoices):
        SUBMISSION = "submission", "Submission"
        STATUS_CHANGE = "status_change", "Status change"
        OWNER_CHANGE = "owner_change", "Owner change"
        NOTE = "note", "Note"
        EMAIL_SENT = "email_sent", "Email sent"
        ESCALATED = "escalated", "Escalated"
        NDA = "nda", "NDA"
        EVALUATION = "evaluation", "Evaluation"
        POC = "poc", "PoC"
        PAID_EVAL = "paid_eval", "Paid evaluation"
        MEETING = "meeting", "Meeting"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    type = models.CharField(max_length=20, choices=ActivityType.choices)
    label = models.CharField(max_length=255)
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_activities",
    )
    by_name = models.CharField(max_length=200, blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Lead activities"

    def __str__(self) -> str:
        return f"LeadActivity({self.type}, {self.lead_id})"
