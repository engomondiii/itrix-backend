"""
Customer-success models — the State 10 domain (Backend v6.0 §Phase 2, Architecture §7).

THE PRIORITY RULE governs everything in this module:

    Keeping paying customers happy and successful is more important than moving them
    toward another agreement. This is NOT an upsell surface.

Two design decisions follow directly from it, and both are enforced by the schema rather
than by convention:

1. ``Outcome`` statuses are the CUSTOMER's outcomes — On plan / At risk / Off plan /
   Achieved. There is deliberately no field for an internal sales target, a pipeline
   stage, or a commercial probability. If it isn't a column, it can't leak into a
   customer-facing serializer by accident.

2. ``FeedbackPulse`` has no field that renders a score back to the customer. A pulse is
   private to the success owner, is never used in copy addressed to the customer, and is
   never shown outside the success team (§12I).

── ACTIVATION AT FIRST PAYMENT ──────────────────────────────────────────────
R16: customer-success modules activate at the FIRST PAYMENT, not at license-out. A paid
Assessment customer (State 7) already has named owners, support access and success
goals. ``overlay.activate()`` is what makes that true.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class OutcomeStatus(models.TextChoices):
    """
    The four status words, used EXACTLY as written (Playbook v1.6 §12B).

    Not "green/amber/red", not a percentage. These words are what the customer reads,
    and they were chosen so that "Off plan" cannot be softened into "progressing".
    """

    ON_PLAN = "on_plan", "On plan"
    AT_RISK = "at_risk", "At risk"
    OFF_PLAN = "off_plan", "Off plan"
    ACHIEVED = "achieved", "Achieved"


class Outcome(BaseModel):
    """
    An outcome the customer and itriX agreed together.

    ``owner_side`` records who owns it on WHICH side. Dependencies that need something
    from the customer are flagged early so they do not surprise anyone (§12F).
    """

    class OwnerSide(models.TextChoices):
        ITRIX = "itrix", "itriX"
        CUSTOMER = "customer", "Customer"
        SHARED = "shared", "Shared"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="outcomes"
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=OutcomeStatus.choices,
        default=OutcomeStatus.ON_PLAN,
        db_index=True,
    )
    # What we are measuring, in the customer's terms. Qualitative by default: a numeric
    # target before a PoC has proven it would be a performance claim.
    measure = models.CharField(max_length=300, blank=True, default="")
    owner_side = models.CharField(
        max_length=16, choices=OwnerSide.choices, default=OwnerSide.SHARED
    )
    owner_name = models.CharField(max_length=200, blank=True, default="")
    target_date = models.DateField(null=True, blank=True)
    achieved_at = models.DateTimeField(null=True, blank=True)
    # Why the status is what it is — shown to the customer, so it must be plain.
    status_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["target_date", "-created_at"]
        verbose_name = "Outcome"
        verbose_name_plural = "Outcomes"
        indexes = [models.Index(fields=["client", "status"])]

    def __str__(self) -> str:
        return f"Outcome({self.client_id}: {self.title[:40]} = {self.status})"

    @property
    def is_off_plan(self) -> bool:
        """Feeds the customer-first NBA rule: an off-plan outcome outranks expansion."""
        return self.status in (OutcomeStatus.OFF_PLAN, OutcomeStatus.AT_RISK)


class SuccessPlan(BaseModel):
    """The shared 30/60/90 plan (§12F)."""

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="success_plans"
    )
    title = models.CharField(max_length=300, default="Our shared plan")
    summary = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    starts_on = models.DateField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Success plan"
        verbose_name_plural = "Success plans"

    def __str__(self) -> str:
        return f"SuccessPlan({self.client_id}: {self.title[:40]})"


class SuccessPlanMilestone(BaseModel):
    """
    One 30/60/90 milestone.

    ``needs_customer_action`` exists so dependencies can be surfaced EARLY rather than
    discovered at the review. A plan that quietly waits on the customer and then reports
    itself as behind is a plan that damaged trust to protect a status field.
    """

    class Horizon(models.IntegerChoices):
        DAYS_30 = 30, "30 days"
        DAYS_60 = 60, "60 days"
        DAYS_90 = 90, "90 days"

    plan = models.ForeignKey(
        SuccessPlan, on_delete=models.CASCADE, related_name="milestones"
    )
    horizon = models.PositiveSmallIntegerField(
        choices=Horizon.choices, default=Horizon.DAYS_30, db_index=True
    )
    title = models.CharField(max_length=300)
    owner_side = models.CharField(
        max_length=16, choices=Outcome.OwnerSide.choices, default=Outcome.OwnerSide.SHARED
    )
    owner_name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=OutcomeStatus.choices, default=OutcomeStatus.ON_PLAN
    )
    needs_customer_action = models.BooleanField(default=False)
    due_on = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["horizon", "due_on", "created_at"]
        verbose_name = "Success plan milestone"
        verbose_name_plural = "Success plan milestones"

    def __str__(self) -> str:
        return f"Milestone({self.horizon}d: {self.title[:40]})"


class DeploymentHealth(BaseModel):
    """
    Operational status of one deployment (§12C).

    ``known_limitations`` is a first-class field, not a note. The framing in the Playbook
    is deliberate: "These are the limitations we already know about. We would rather you
    hear them from us." A schema without somewhere to put them makes that promise
    impossible to keep.
    """

    class Status(models.TextChoices):
        HEALTHY = "healthy", "Healthy"
        DEGRADED = "degraded", "Degraded"
        DOWN = "down", "Down"
        UNKNOWN = "unknown", "Unknown"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="deployments"
    )
    environment = models.CharField(max_length=120, default="production")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UNKNOWN, db_index=True
    )
    version = models.CharField(max_length=64, blank=True, default="")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    incident_note = models.TextField(blank=True, default="")
    known_limitations = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["client", "environment"]
        verbose_name = "Deployment health"
        verbose_name_plural = "Deployment health"
        indexes = [models.Index(fields=["client", "status"])]

    def __str__(self) -> str:
        return f"Deployment({self.client_id}/{self.environment}: {self.status})"


class SupportRequest(BaseModel):
    """
    One support request (§12D).

    ``blocking`` is the field the customer-first NBA rule reads. A blocking, unresolved
    request makes a support action PRIMARY and suppresses every commercial one — that is
    a defect check, not a judgement call (§18.7).

    NEVER SELL INTO A SUPPORT THREAD. A support reply helps with the problem and stops.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING_ON_CUSTOMER = "waiting_on_customer", "Waiting on customer"
        RESOLVED = "resolved", "Resolved"

    class Urgency(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="support_requests"
    )
    thread_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    urgency = models.CharField(
        max_length=16, choices=Urgency.choices, default=Urgency.NORMAL, db_index=True
    )
    # Blocking = the customer cannot proceed. Drives NBA suppression.
    blocking = models.BooleanField(default=False, db_index=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_requests",
    )
    owner_name = models.CharField(max_length=200, blank=True, default="")
    sla_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")
    # "Did this actually resolve it for you?" — asked after resolution (§12D).
    customer_confirmed_resolved = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Support request"
        verbose_name_plural = "Support requests"
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["status", "sla_due_at"]),
        ]

    def __str__(self) -> str:
        return f"SupportRequest({self.client_id}: {self.subject[:40]} [{self.status}])"

    @property
    def is_open(self) -> bool:
        return self.status != self.Status.RESOLVED

    @property
    def is_blocking_open(self) -> bool:
        return self.blocking and self.is_open


class FeedbackPulse(BaseModel):
    """
    Private customer feedback (§12I).

    THREE RULES, all enforced here rather than downstream:

    1. ``score`` is NEVER rendered back to the customer as a judgement about them.
    2. It is never used in copy addressed to them.
    3. It is never shown outside the success team.

    The customer-facing serializer has no field for ``score`` at all — see
    ``serializers.py``. The write endpoint is write-only: a customer can submit a pulse
    and cannot read one back, which is what makes "this is private" true rather than
    aspirational.
    """

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="feedback_pulses"
    )
    # 1-5, internal only. Nullable because free text alone is a valid pulse.
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    wants_follow_up = models.BooleanField(default=False)
    # Set by the success owner, never by the customer.
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_pulses",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Feedback pulse"
        verbose_name_plural = "Feedback pulses"
        indexes = [models.Index(fields=["client", "-created_at"])]

    def __str__(self) -> str:
        return f"FeedbackPulse({self.client_id} @ {self.created_at:%Y-%m-%d})"

    @property
    def is_negative(self) -> bool:
        """A negative trust signal — makes human outreach primary in the NBA rule."""
        return self.score is not None and self.score <= 2


class RelationshipTeamMember(BaseModel):
    """
    A named human on the customer's relationship team (§12H).

    AN ABSOLUTE: a customer can always reach a named human without first negotiating
    with an agent. This table is what makes "named" literal — the header renders a name
    and a role, and if this table is empty the header has nothing honest to show.
    """

    class Role(models.TextChoices):
        CUSTOMER_SUCCESS = "customer_success", "Customer success"
        TECHNICAL = "technical", "Technical"
        EXECUTIVE = "executive", "Executive"
        SUPPORT = "support", "Support"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="relationship_team"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_relationships",
    )
    display_name = models.CharField(max_length=200)
    role = models.CharField(max_length=24, choices=Role.choices, db_index=True)
    # What they can help with, in plain language.
    helps_with = models.CharField(max_length=300, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["role", "-is_primary", "display_name"]
        verbose_name = "Relationship team member"
        verbose_name_plural = "Relationship team"
        indexes = [models.Index(fields=["client", "role"])]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.role}) for {self.client_id}"


class ReleaseNote(BaseModel):
    """A release note visible to contracted customers (§12G)."""

    version = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    released_at = models.DateTimeField(db_index=True)
    # Scope to one customer, or leave blank for all contracted customers.
    customer_scope = models.CharField(max_length=64, blank=True, default="", db_index=True)
    is_published = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-released_at"]
        verbose_name = "Release note"
        verbose_name_plural = "Release notes"

    def __str__(self) -> str:
        return f"ReleaseNote({self.version}: {self.title[:40]})"


class ChangeLogEntry(BaseModel):
    """
    One thing that changed since the customer's last visit (§12E).

    Includes items WAITING ON A DECISION FROM THEM. A digest that only reports our own
    completed work is a progress report, not a change log — and it hides the thing the
    customer most needs to see.
    """

    class Kind(models.TextChoices):
        COMPLETED = "completed", "Work completed"
        RESOLVED = "resolved", "Issue resolved"
        SHIPPED = "shipped", "Update shipped"
        AWAITING_DECISION = "awaiting_decision", "Waiting on your decision"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="change_log"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    title = models.CharField(max_length=300)
    detail = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(db_index=True)
    # Set once the customer has seen it in a digest.
    surfaced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Change log entry"
        verbose_name_plural = "Change log"
        indexes = [models.Index(fields=["client", "-occurred_at"])]

    def __str__(self) -> str:
        return f"ChangeLogEntry({self.client_id}: {self.kind} {self.title[:30]})"


class SuccessReview(BaseModel):
    """
    A scheduled success review (§12 "Next review").

    Carries its agenda so the customer can see what will be discussed before they walk
    in. A review whose agenda appears only on the day is a meeting, not a partnership.
    """

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="success_reviews"
    )
    scheduled_at = models.DateTimeField(db_index=True)
    agenda = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        verbose_name = "Success review"
        verbose_name_plural = "Success reviews"

    def __str__(self) -> str:
        return f"SuccessReview({self.client_id} @ {self.scheduled_at:%Y-%m-%d})"
