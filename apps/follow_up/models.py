"""
Follow-up models.

``FollowUpTask`` tracks the SLA clock for a lead: it's created when a lead is created (the
SLA clock starts at ``created_at``), its ``due_at`` derives from the tier SLA, and the team
completes or snoozes it. Matches the dashboard's ``FollowUpTask`` type
(``{id, leadId, leadName, company, tier, owner, createdAt, dueAt, status, snoozedUntil?, note?}``).
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class FollowUpStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    SNOOZED = "snoozed", "Snoozed"
    DISMISSED = "dismissed", "Dismissed"


class FollowUpTask(BaseModel):
    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.CASCADE, related_name="follow_up_tasks"
    )
    # Denormalised for fast list rendering (matches the dashboard card).
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    tier = models.PositiveSmallIntegerField(default=4)
    owner = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_up_tasks",
    )

    due_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=12, choices=FollowUpStatus.choices, default=FollowUpStatus.PENDING, db_index=True
    )
    snoozed_until = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    breach_notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["due_at"]
        verbose_name = "Follow-up task"
        verbose_name_plural = "Follow-up tasks"
        indexes = [models.Index(fields=["status", "due_at"])]

    def __str__(self) -> str:
        return f"FollowUpTask(lead={self.lead_id}, due={self.due_at:%Y-%m-%d}, {self.status})"

    @property
    def effective_due(self):
        return self.snoozed_until or self.due_at

    def is_overdue(self, *, now=None) -> bool:
        from django.utils import timezone

        now = now or timezone.now()
        return self.status == FollowUpStatus.PENDING and self.effective_due < now
