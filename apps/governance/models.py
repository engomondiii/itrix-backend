"""
Governance models (Backend v4 §5.2, §6).

The Claim-Card fabric sits on top of the shipped guards (disclosure_filter,
prohibited_language_checker, hallucination_guard, ClaimRecord). It formalizes the
5-level approval matrix: every serious claim is pre-registered with approved wording and
an approval owner, and every outbound message that exceeds the auto-approve threshold is
queued as an ``ApprovalRequest`` for a human.

    ClaimCard        — a pre-registered claim: approved wording, claim level, owner.
    ApprovalRequest  — a queued outbound message awaiting human approval (with the
                       L4/L5 second-approver rule), the audit spine of the queue.

The 5-level matrix (claim levels):
    L1 — conversational / qualitative framing (auto)
    L2 — qualitative product/fit narrative (auto, ≤ AGENT_AUTO_APPROVE_MAX_LEVEL)
    L3 — drafts needing citation / objection handling (human approval)
    L4 — commercial / competitive claims (human approval + second approver)
    L5 — legal / binding document outlines (always human + second approver)
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


# The five claim levels, single-sourced here (mirrored by Surface 2 constants).
CLAIM_LEVELS = (1, 2, 3, 4, 5)

# Levels that require a distinct SECOND approver before delivery.
SECOND_APPROVER_LEVELS = {4, 5}


class ClaimLevel(models.IntegerChoices):
    L1 = 1, "L1 — conversational"
    L2 = 2, "L2 — qualitative narrative"
    L3 = 3, "L3 — draft (citation required)"
    L4 = 4, "L4 — commercial / competitive"
    L5 = 5, "L5 — legal / binding (draft only)"


class ClaimCard(BaseModel):
    """A pre-registered claim with approved wording + an approval owner."""

    key = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    approved_wording = models.TextField(
        help_text="The exact wording an agent may use for this claim."
    )
    claim_level = models.PositiveSmallIntegerField(
        choices=ClaimLevel.choices, default=ClaimLevel.L2
    )
    # Optional linkage to the knowledge_core ClaimRecord this card governs.
    claim_record_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_claim_cards",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["claim_level", "key"]
        verbose_name = "Claim card"
        verbose_name_plural = "Claim cards"
        indexes = [
            models.Index(fields=["claim_level", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"ClaimCard({self.key}, L{self.claim_level})"


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    EDITED = "edited", "Approved with edits"
    REJECTED = "rejected", "Rejected"
    AWAITING_SECOND = "awaiting_second", "Awaiting second approver"


class ApprovalRequest(BaseModel):
    """
    A queued outbound message awaiting human approval.

    Created by the runtime/fan-out when an agent or team→client message exceeds the
    auto-approve threshold. Approving it flips the linked conversation Message to
    APPROVED and (for L4/L5) requires a distinct second approver.
    """

    # Link to the held conversation message (the durable draft).
    message_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    conversation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
    )
    client_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    agent_key = models.CharField(max_length=64, blank=True, default="")
    claim_level = models.PositiveSmallIntegerField(choices=ClaimLevel.choices, default=ClaimLevel.L3)

    draft_body = models.TextField(blank=True, default="")
    final_body = models.TextField(blank=True, default="")
    cited_chunk_ids = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING, db_index=True
    )
    reason = models.TextField(blank=True, default="")

    # Approvers (L4/L5 need two distinct people).
    first_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="first_approvals",
    )
    second_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="second_approvals",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Approval request"
        verbose_name_plural = "Approval requests"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["claim_level", "status"]),
        ]

    def __str__(self) -> str:
        return f"ApprovalRequest(L{self.claim_level}, {self.status}, msg={self.message_id})"

    @property
    def requires_second_approver(self) -> bool:
        return self.claim_level in SECOND_APPROVER_LEVELS

    @property
    def is_resolved(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.EDITED, ApprovalStatus.REJECTED)
