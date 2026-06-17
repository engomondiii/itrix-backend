"""
NDA models.

``NDARecord`` tracks an NDA through required → sent → signed, with a small checklist. One
NDA per lead. Matches the dashboard's ``NDARecord`` type
(``{id, leadId, leadName, company, status, checklist[], requestedAt, signedAt?}``).
The checklist is stored as JSON (list of ``{id, label, done}``).
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class NDAStatus(models.TextChoices):
    REQUIRED = "required", "Required"
    SENT = "sent", "Sent"
    SIGNED = "signed", "Signed"


class NDARecord(BaseModel):
    lead = models.OneToOneField(
        "leads.Lead", on_delete=models.CASCADE, related_name="nda"
    )
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=12, choices=NDAStatus.choices, default=NDAStatus.REQUIRED)
    checklist = models.JSONField(default=list, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "NDA record"
        verbose_name_plural = "NDA records"

    def __str__(self) -> str:
        return f"NDA({self.lead_name or self.lead_id}, {self.status})"
