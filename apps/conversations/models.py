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
    # v6.0 fifth context (Architecture v2.6 §14.2): an unidentified visitor talking to
    # the Concierge on the public plane. Public ceiling, HARD-CAPPED; the stream guard
    # is mandatory; no commitment cards until value has been delivered.
    ANONYMOUS_REVIEW = "anonymous_review", "Anonymous review (public plane)"
    CLIENT_PAGE = "client_page", "Client page"
    PORTAL = "portal", "Portal (client)"
    CUSTOMER_SUCCESS = "customer_success", "Customer success"
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


class StreamingStatus(models.TextChoices):
    """
    Where a message sits in the three-part streaming governance model (§19.8).

        pending      queued, nothing streamed yet
        streaming    tokens are being emitted under the stream guard
        settled      generation finished and the full Claim-Card pipeline passed
        halted       the stream guard matched a prohibited pattern and hard-stopped;
                     the partial text was discarded from the client
        under_review the settle-time gate rejected it; approved wording replaced it
    """

    PENDING = "pending", "Pending"
    STREAMING = "streaming", "Streaming"
    SETTLED = "settled", "Settled"
    HALTED = "halted", "Halted"
    UNDER_REVIEW = "under_review", "Under review"


class Message(BaseModel):
    """One turn in a conversation."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    # ── v6.0 conversation spine ──────────────────────────────────────────────
    thread = models.ForeignKey(
        "conversations.Thread",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
    )
    # Monotonic per thread. Every message.delta carries this so a client that detects a
    # gap re-fetches rather than rendering a hole, and a reconnect resumes from the last
    # acknowledged seq (Architecture v2.6 §14.4).
    seq = models.PositiveIntegerField(default=0, db_index=True)
    streaming_status = models.CharField(
        max_length=16,
        choices=StreamingStatus.choices,
        default=StreamingStatus.SETTLED,
        db_index=True,
    )
    # When this message is a rolling summary, the (inclusive) seq range it replaces.
    summary_of = models.JSONField(null=True, blank=True)
    # What could NOT be considered for this turn. Never silently dropped: if material
    # content did not fit the context budget, the turn says so plainly (§12.5).
    context_note = models.TextField(blank=True, default="")
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


class MessageAttachment(BaseModel):
    """
    Links an attachment to the turn it was sent with (Backend v6.0 §Phase 2).

    ``attachment_id`` is a plain char field rather than a FK so ``conversations`` does
    not gain a hard dependency on ``attachments``. The attachments app is flag-gated; a
    deployment running with ENABLE_ATTACHMENTS off should not be forced to install its
    tables to send a message.
    """

    message = models.ForeignKey(
        "conversations.Message", on_delete=models.CASCADE, related_name="attachment_links"
    )
    attachment_id = models.CharField(max_length=64, db_index=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "created_at"]
        verbose_name = "Message attachment"
        verbose_name_plural = "Message attachments"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "attachment_id"], name="uniq_attachment_per_message"
            )
        ]

    def __str__(self) -> str:
        return f"MessageAttachment({self.message_id} -> {self.attachment_id})"


# ─────────────────────────────────────────────────────────────────────────────
# Message length (Backend v6.0 §2.3)
# ─────────────────────────────────────────────────────────────────────────────
# There is NO user-facing limit. MAX_MESSAGE_CHARS is a server SAFETY cap that returns
# 413 with a specific, actionable message. Long threads are handled by the context
# budget (services/context_assembly.py), never by refusing the visitor's problem.


class MessageTooLong(Exception):
    """Raised when a turn exceeds the server safety cap. Maps to HTTP 413."""

    def __init__(self, length: int, limit: int):
        self.length = length
        self.limit = limit
        super().__init__(
            f"That message is {length:,} characters, which is longer than we can accept "
            f"in one turn ({limit:,}). Splitting it into two messages will work, and "
            f"nothing you have already written is lost."
        )


def max_message_chars() -> int:
    from django.conf import settings

    return int(getattr(settings, "MAX_MESSAGE_CHARS", 100_000))


def validate_message_length(body: str) -> str:
    """Raise ``MessageTooLong`` above the safety cap; otherwise return the body."""
    text = body or ""
    limit = max_message_chars()
    if len(text) > limit:
        raise MessageTooLong(len(text), limit)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# The v6.0 conversation spine
# ─────────────────────────────────────────────────────────────────────────────
# Thread / ThreadParticipant live in ``models_thread.py`` for review clarity but MUST be
# imported here so Django registers them under the ``conversations`` app label.
from apps.conversations.models_thread import (  # noqa: E402,F401  (re-export)
    Thread,
    ThreadContext,
    ThreadOwnerKind,
    ThreadParticipant,
    ThreadTitleSource,
)

__all__ = [
    "Conversation",
    "ConversationContext",
    "GovernanceStatus",
    "Message",
    "MessageAttachment",
    "Participant",
    "SenderKind",
    "StreamingStatus",
    "Thread",
    "ThreadContext",
    "ThreadOwnerKind",
    "ThreadParticipant",
    "ThreadTitleSource",
    "max_message_chars",
    "MessageTooLong",
    "validate_message_length",
]
