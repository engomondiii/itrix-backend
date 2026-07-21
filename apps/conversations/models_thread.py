"""
The conversation spine — Thread + ThreadParticipant (Backend v6.0 §2.1).

Kept in a separate module from ``models.py`` for review clarity (the spec asks for this
explicitly) and imported into ``models.py`` so Django's app registry finds them under
the ``conversations`` app label.

── WHY A THREAD AND NOT JUST A CONVERSATION ─────────────────────────────────
The shipped ``Conversation`` model is scoped to a CONTEXT (review / client_page / portal
/ console) and to a subject. In v2.6 the visitor never leaves the surface they started
on: what used to be four contexts on four screens is ONE continuous thread that changes
state. So the Thread is the durable spine — it owns the turns, the artifacts and the
attachments across every state from 1 to 10 — while Conversation remains as the
transport-level grouping the shipped realtime layer already understands.

A Thread therefore OUTLIVES its context. A visitor's anonymous thread at State 1 is the
same row they are still reading at State 10 as a contracted customer.

── ANONYMOUS OWNERSHIP ──────────────────────────────────────────────────────
A thread created by an unidentified visitor is owned by the SIGNED VISITOR SESSION. It
is listed only to that session, retained for ANON_THREAD_RETENTION_DAYS, and purged on
expiry. On invite consumption the thread is CLAIMED — migrated to the Client with every
turn, artifact and attachment preserved (``services/claim.py``).

A claim never merges threads across sessions and never links two anonymous sessions to
each other. That is a privacy boundary, not an optimisation.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class ThreadOwnerKind(models.TextChoices):
    """Who owns this thread. Exactly one of the owner FKs is set, by kind."""

    SESSION = "session", "Visitor session (anonymous)"
    CLIENT = "client", "Client"
    TEAM = "team", "Team"


class ThreadContext(models.TextChoices):
    """
    The conversation contexts (Architecture v2.6 §14.2).

    ``anonymous_review`` is the FIFTH context added in v6.0: an unidentified visitor
    talking to the Concierge on the public plane, hard-capped at the public ceiling with
    the stream guard mandatory and no commitment cards until value is delivered.
    """

    REVIEW = "review", "Review"
    ANONYMOUS_REVIEW = "anonymous_review", "Anonymous review"
    CLIENT_PAGE = "client_page", "Client page"
    PORTAL = "portal", "Portal"
    CUSTOMER_SUCCESS = "customer_success", "Customer success"


class ThreadTitleSource(models.TextChoices):
    GENERATED = "generated", "Generated"
    USER = "user", "User"


class Thread(BaseModel):
    """
    One continuous conversation, from the first sentence to the tenth state.

    ``retention_expires_at`` is set only while the thread is anonymous; claiming it
    clears the field (the client's contractual retention takes over).
    """

    owner_kind = models.CharField(
        max_length=16,
        choices=ThreadOwnerKind.choices,
        default=ThreadOwnerKind.SESSION,
        db_index=True,
    )
    # The signed visitor-session id that owns an anonymous thread. Not a FK: the session
    # is a signed cookie value, not a row, and must not outlive its retention window.
    visitor_session = models.CharField(max_length=64, blank=True, default="", db_index=True)
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="threads",
    )
    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="threads",
    )
    # The transport-level Conversation this thread's messages hang off. Nullable so a
    # thread can exist before the realtime layer has grouped it.
    conversation = models.OneToOneField(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="thread",
    )

    context = models.CharField(
        max_length=24,
        choices=ThreadContext.choices,
        default=ThreadContext.ANONYMOUS_REVIEW,
        db_index=True,
    )
    title = models.CharField(max_length=200, blank=True, default="")
    title_source = models.CharField(
        max_length=16,
        choices=ThreadTitleSource.choices,
        default=ThreadTitleSource.GENERATED,
    )
    # The journey state at creation time — useful for cohorting without replaying
    # the transition log.
    state_at_creation = models.CharField(max_length=20, blank=True, default="ARRIVED")

    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-last_activity_at", "-created_at"]
        verbose_name = "Thread"
        verbose_name_plural = "Threads"
        indexes = [
            models.Index(fields=["visitor_session", "-last_activity_at"]),
            models.Index(fields=["client", "-last_activity_at"]),
            models.Index(fields=["owner_kind", "context"]),
            models.Index(fields=["retention_expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Thread({self.id}, {self.owner_kind}, {self.context})"

    @property
    def group_name(self) -> str:
        """The Channels group for this thread's realtime fan-out."""
        return f"thread.{self.id}"

    @property
    def is_anonymous(self) -> bool:
        return self.owner_kind == ThreadOwnerKind.SESSION and self.client_id is None

    @property
    def is_claimed(self) -> bool:
        return self.claimed_at is not None


class ThreadParticipant(BaseModel):
    """
    A principal attached to a thread.

    ``principal_id`` is intentionally a plain string rather than a set of nullable FKs:
    a participant may be a visitor session (not a row), an agent (not a row), a Client,
    or a team User. One column keeps the join simple and avoids four mutually-exclusive
    nullable columns that no constraint could keep honest.
    """

    class PrincipalKind(models.TextChoices):
        SESSION = "session", "Visitor session"
        CLIENT = "client", "Client"
        USER = "user", "Team user"
        AGENT = "agent", "Agent"

    class Role(models.TextChoices):
        VISITOR = "visitor", "Visitor"
        AGENT = "agent", "Agent"
        TEAM = "team", "Team"

    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, related_name="participants"
    )
    principal_kind = models.CharField(max_length=16, choices=PrincipalKind.choices)
    principal_id = models.CharField(max_length=128)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VISITOR)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thread participant"
        verbose_name_plural = "Thread participants"
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "principal_kind", "principal_id"],
                name="uniq_thread_participant",
            )
        ]
        indexes = [models.Index(fields=["thread", "role"])]

    def __str__(self) -> str:
        return f"ThreadParticipant({self.principal_kind}:{self.principal_id} in {self.thread_id})"
