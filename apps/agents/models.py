"""
Agent models.

``AgentRun`` is the audit record of a single agent invocation: which agent, for which
lead/client, the input context digest, the output, whether the AI path or the
deterministic fallback was used, the governance outcome, and timing. Every runtime
invocation writes one row (best-effort) so the S2 console and analytics can see exactly
what each agent did.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class AgentRun(BaseModel):
    class Status(models.TextChoices):
        OK = "ok", "OK"
        FALLBACK = "fallback", "Deterministic fallback"
        ERROR = "error", "Error"

    class Governance(models.TextChoices):
        AUTO_APPROVED = "auto_approved", "Auto-approved"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        BLOCKED = "blocked", "Blocked"

    agent_key = models.CharField(max_length=64, db_index=True)
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    client_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OK)
    used_ai = models.BooleanField(default=False)
    governance_status = models.CharField(
        max_length=16, choices=Governance.choices, default=Governance.AUTO_APPROVED
    )
    claim_level = models.PositiveSmallIntegerField(default=0)

    # Compact I/O for audit — not the full transcript.
    input_summary = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    chunk_ids = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent run"
        verbose_name_plural = "Agent runs"
        indexes = [
            models.Index(fields=["agent_key", "created_at"]),
            models.Index(fields=["lead", "agent_key"]),
        ]

    def __str__(self) -> str:
        return f"AgentRun({self.agent_key}, {self.status}, lead={self.lead_id})"
