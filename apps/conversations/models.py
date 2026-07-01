"""
Conversation models (Backend v4 §1.3, §4).

Durable, auditable chat across three contexts (review, client_page, portal). Every
message a visitor/client sends and every agent/team reply is persisted here — the
WebSocket layer is transport, this is the record of truth. Governance status lives on
each message so the "under review" state is durable, not just a transient WS event.

    Conversation  — a thread, scoped to a context + subject (lead and/or client).
    Message       — one turn: who sent it, the body, citations, governance status.
    Participant   — a subject/agent/team member attached to a conversation (presence,
                    unread tracking, and authorization to post).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class ConversationContext(models.TextChoices):
    REVIEW = "review", "Review (anonymous)"
    CLIENT_PAGE = "client_page", "Client page"
    PORTAL = "portal", "Portal (client)"
    CONSOLE = "console", "Team console"


class SenderKind(models.TextChoices):
    VISITOR = "visitor", "Visitor (anonymous)"
    CLIENT = "client", "Client"
    AGENT = "agent", "Agent"
    TEAM = "team", "Team"
    SYSTEM = "system", "System"


class GovernanceStatus(models.TextChoices):
    AUTO_APPROVED = "auto_approved", "Auto-approved"
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    BLOCKED = "blocked", "Blocked"


class Conversation(BaseModel):
    """A durable chat thread scoped to a context + subject."""

    context = models.CharField(
        max_length=16, choices=ConversationContext.choices, db_index=True
    )
    # Subject linkage — a review/client_page thread is keyed by lead; a portal thread by
    # client (which also links back to a lead). Either may be blank for a console thread.
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    # For review threads before a lead exists, we key by the review session id.
    review_session_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    title = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"
        indexes = [
            models.Index(fields=["context", "lead"]),
            models.Index(fields=["context", "client"]),
            models.Index(fields=["review_session_id"]),
        ]

    def __str__(self) -> str:
        return f"Conversation({self.context}, lead={self.lead_id}, client={self.client_id})"

    @property
    def group_name(self) -> str:
        """The Channels group name for this conversation (realtime fan-out target)."""
        return f"conv.{self.id}"


class Message(BaseModel):
    """One turn in a conversation."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender_kind = models.CharField(max_length=16, choices=SenderKind.choices, db_index=True)
    # Optional concrete sender references (only one is set, by kind).
    sender_client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_messages"
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_client_messages",
    )
    agent_key = models.CharField(max_length=64, blank=True, default="")

    body = models.TextField(blank=True, default="")
    # Governance: an agent/team message may be held before delivery.
    governance_status = models.CharField(
        max_length=16,
        choices=GovernanceStatus.choices,
        default=GovernanceStatus.AUTO_APPROVED,
        db_index=True,
    )
    claim_level = models.PositiveSmallIntegerField(default=0)
    cited_chunk_ids = models.JSONField(default=list, blank=True)
    # Link back to the AgentRun that produced an agent message (audit).
    agent_run_id = models.CharField(max_length=64, blank=True, default="")
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["governance_status"]),
        ]

    def __str__(self) -> str:
        return f"Message({self.sender_kind}, conv={self.conversation_id})"

    @property
    def is_deliverable(self) -> bool:
        """A message is visible to the client only once it is approved/auto-approved."""
        return self.governance_status in (
            GovernanceStatus.AUTO_APPROVED,
            GovernanceStatus.APPROVED,
        )


class Participant(BaseModel):
    """A subject/agent/team member attached to a conversation."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participants"
    )
    kind = models.CharField(max_length=16, choices=SenderKind.choices)
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, null=True, blank=True, related_name="participations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversation_participations",
    )
    display_name = models.CharField(max_length=200, blank=True, default="")
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Participant"
        verbose_name_plural = "Participants"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "kind", "client", "user"],
                name="uniq_participant_per_conversation",
            )
        ]

    def __str__(self) -> str:
        return f"Participant({self.kind}, conv={self.conversation_id})"
