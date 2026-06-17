"""
Email models.

``EmailLog`` records every email the system builds/sends (visitor confirmations, internal
alerts, follow-ups), so the team has an audit trail and the dashboard can show what went
out. When ``ENABLE_EMAIL_DELIVERY`` is off, emails are still *built and logged* with a
``stubbed`` status — nothing is actually sent, but the workflow is exercised end-to-end.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class EmailLog(BaseModel):
    class Kind(models.TextChoices):
        CONFIRMATION = "confirmation", "Visitor confirmation"
        INTERNAL_ALERT = "internal_alert", "Internal alert"
        FOLLOW_UP = "follow_up", "Follow-up"
        VISITOR = "visitor", "Visitor (generic)"

    class Status(models.TextChoices):
        STUBBED = "stubbed", "Stubbed (delivery disabled)"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    to_email = models.EmailField()
    from_email = models.EmailField(blank=True, default="")
    subject = models.CharField(max_length=512)
    body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.STUBBED)
    error = models.TextField(blank=True, default="")
    provider_message_id = models.CharField(max_length=255, blank=True, default="")

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emails",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Email log"
        verbose_name_plural = "Email logs"

    def __str__(self) -> str:
        return f"EmailLog({self.kind} -> {self.to_email}, {self.status})"
