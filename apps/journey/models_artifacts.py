"""
Artifact registry models (Backend v6.0 §3.3, Architecture §2.5).

    An ARTIFACT is a governed, structured payload rendered as an EXPANDABLE BLOCK INSIDE
    THE TRANSCRIPT. It has a type, a disclosure level, a governance status and an
    optional deep-link.

── THE IN-THREAD RENDERING IS PRIMARY, BY CONTRACT ──────────────────────────
An artifact MAY additionally be reachable at a dedicated route — for emailing, sharing
under a capability token, or printing. But the risk register is explicit about what goes
wrong if that inverts:

    Deep-linked artifacts become the real interface and the thread decays.

So ``capability_token`` is nullable and the route is an ALTERNATIVE VIEW. Nothing in this
model makes the deep-link required, and nothing lets it become the only way to see the
content.

── REGENERATION SUPERSEDES, NEVER OVERWRITES ────────────────────────────────
``superseded_by`` preserves the audit trail. A Boundary Waste Map that was regenerated
after new evidence is a different document from the one the customer read last week, and
both need to exist.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel
from apps.journey.constants import ARTIFACT_TYPES


class Artifact(BaseModel):
    """One governed payload delivered into a thread."""

    class GovernanceStatus(models.TextChoices):
        AUTO_APPROVED = "auto_approved", "Auto-approved"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        BLOCKED = "blocked", "Blocked"

    thread = models.ForeignKey(
        "conversations.Thread", on_delete=models.CASCADE, related_name="artifacts"
    )
    # Validated against constants.ARTIFACT_TYPES on save — an unknown type is a server
    # error, not a generic render (§3.9: "a generic renderer would display a payload
    # nobody designed a disclosure review for").
    type = models.CharField(max_length=32, db_index=True)
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField(default=dict, blank=True)

    disclosure_level = models.CharField(max_length=24, default="public", db_index=True)
    governance_status = models.CharField(
        max_length=16,
        choices=GovernanceStatus.choices,
        default=GovernanceStatus.AUTO_APPROVED,
        db_index=True,
    )

    # Binds the artifact to a shareable URL. An artifact token grants reach to THIS
    # artifact's read endpoint only — never the ability to post a turn to the thread that
    # produced it (§3.3).
    capability_token = models.TextField(blank=True, default="")
    generated_by_run = models.CharField(max_length=64, blank=True, default="")
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes"
    )
    # State 10's success_overview is PINNED to the top of the thread (§17.3).
    pinned = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Artifact"
        verbose_name_plural = "Artifacts"
        indexes = [
            models.Index(fields=["thread", "type"]),
            models.Index(fields=["type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Artifact({self.type} v{self.version} on {self.thread_id})"

    def save(self, *args, **kwargs):
        if self.type not in ARTIFACT_TYPES:
            raise ValueError(
                f"Unknown artifact type {self.type!r}. "
                f"Allowed: {sorted(ARTIFACT_TYPES)}"
            )
        return super().save(*args, **kwargs)

    @property
    def is_current(self) -> bool:
        return self.superseded_by_id is None

    @property
    def is_deliverable(self) -> bool:
        return self.governance_status in (
            self.GovernanceStatus.AUTO_APPROVED,
            self.GovernanceStatus.APPROVED,
        )


class QuestionSuggestion(BaseModel):
    """
    One generated question, with the dimension it targeted.

    ``target_dimension`` exists so the cockpit can audit whether the LOOP WAS PRODUCTIVE
    (§5.4) — three questions that all targeted the same dimension is a broken loop, and
    without this column it looks identical to three good questions.
    """

    thread = models.ForeignKey(
        "conversations.Thread", on_delete=models.CASCADE, related_name="question_suggestions"
    )
    message = models.ForeignKey(
        "conversations.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="question_suggestions",
    )
    primary_text = models.CharField(max_length=500)
    chips = models.JSONField(default=list, blank=True)
    target_dimension = models.CharField(max_length=40, blank=True, default="", db_index=True)
    agent_run_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Question suggestion"
        verbose_name_plural = "Question suggestions"
        indexes = [models.Index(fields=["thread", "created_at"])]

    def __str__(self) -> str:
        return f"QuestionSuggestion({self.target_dimension}: {self.primary_text[:40]})"


class CoverageSnapshot(BaseModel):
    """
    Coverage for one dimension on one thread. INTERNAL-ONLY (§10.5).

    Snapshotted per turn so an operator can see how understanding built up, rather than
    only where it ended.
    """

    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        PARTIAL = "partial", "Partial"
        COVERED = "covered", "Covered"

    thread = models.ForeignKey(
        "conversations.Thread", on_delete=models.CASCADE, related_name="coverage_snapshots"
    )
    dimension = models.CharField(max_length=40, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UNKNOWN, db_index=True
    )
    # Which message covered it — so "why is this covered?" has an answer.
    evidence_message_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "Coverage snapshot"
        verbose_name_plural = "Coverage snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "dimension"], name="uniq_coverage_per_thread_dimension"
            )
        ]

    def __str__(self) -> str:
        return f"CoverageSnapshot({self.thread_id}/{self.dimension}={self.status})"
