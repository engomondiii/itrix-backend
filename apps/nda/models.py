"""
NDA models.

``NDARecord`` tracks an NDA through required → sent → signed (or declined/expired), with
a small checklist and the document itself. One NDA per lead. Matches the dashboard's
``NDARecord`` type (``{id, leadId, leadName, company, status, checklist[], docType, body,
signerName?, signerEmail?, requestedAt, sentAt?, signedAt?, declineReason?}``).
The checklist is stored as JSON (list of ``{id, label, done}``).
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class NDAStatus(models.TextChoices):
    REQUIRED = "required", "Required"
    SENT = "sent", "Sent"
    SIGNED = "signed", "Signed"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"


class NDADocType(models.TextChoices):
    MUTUAL = "mutual", "Mutual NDA"
    ONE_WAY = "one-way", "One-way NDA"


class NDARecord(BaseModel):
    lead = models.OneToOneField(
        "leads.Lead", on_delete=models.CASCADE, related_name="nda"
    )
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=12, choices=NDAStatus.choices, default=NDAStatus.REQUIRED)
    checklist = models.JSONField(default=list, blank=True)
    doc_type = models.CharField(
        max_length=12, choices=NDADocType.choices, default=NDADocType.MUTUAL
    )
    body = models.TextField(blank=True, default="")
    signer_name = models.CharField(max_length=255, blank=True, default="")
    signer_email = models.EmailField(blank=True, default="")
    decline_reason = models.TextField(blank=True, default="")
    requested_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        verbose_name = "NDA record"
        verbose_name_plural = "NDA records"

    def __str__(self) -> str:
        return f"NDA({self.lead_name or self.lead_id}, {self.status})"
