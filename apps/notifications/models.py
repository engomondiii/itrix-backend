"""
Notification model.

In-app notifications shown in the dashboard's notification tray. Matches the dashboard's
``Notification`` type: ``{id, kind, title, body?, href?, read, createdAt}``. The six kinds
correspond to the moments the team cares about (new lead, Tier-1 lead, SLA breach, NDA
signed, escalation, system).
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class Notification(BaseModel):
    class Kind(models.TextChoices):
        NEW_LEAD = "new_lead", "New lead"
        TIER1_LEAD = "tier1_lead", "Tier 1 lead"
        SLA_BREACH = "sla_breach", "SLA breach"
        NDA_SIGNED = "nda_signed", "NDA signed"
        ESCALATION = "escalation", "Escalation"
        SYSTEM = "system", "System"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    href = models.CharField(max_length=512, blank=True, default="")
    read = models.BooleanField(default=False, db_index=True)

    # Optional linkage to the lead that triggered it (for convenience / cleanup).
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes = [models.Index(fields=["read", "created_at"])]

    def __str__(self) -> str:
        return f"Notification({self.kind}: {self.title[:40]})"
