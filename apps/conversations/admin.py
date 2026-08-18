"""
Admin for threads, conversations, messages and participants.

Two containers exist side by side: the legacy ``Conversation`` (context +
subject) and the v6 ``Thread`` (one continuous conversation across journey
states). Both are read-mostly here — the transcripts are evidence and the
cockpit is where they are worked, so this admin exists to *understand* one:
its participants, its artifacts, its coverage, its attachments and its turns,
all from one page.
"""

from __future__ import annotations

from django.contrib import admin

from apps.attachments.models import Attachment
from apps.conversations.models import (
    Conversation,
    Message,
    MessageAttachment,
    Participant,
    Thread,
    ThreadParticipant,
)
from apps.core.admin import (
    AppendOnlyAdmin,
    ItrixModelAdmin,
    ReadOnlyAdmin,
    ReadOnlyTabularInline,
    badge,
    claim_level_badge,
    link_to,
    pretty_json,
    short_id,
    truncate,
)
from apps.journey.models import Artifact, CoverageSnapshot, QuestionSuggestion

# ─────────────────────────────────────────────────────────────────────────────
# Inlines
# ─────────────────────────────────────────────────────────────────────────────


class MessageInline(ReadOnlyTabularInline):
    model = Message
    fk_name = "conversation"
    fields = ("seq", "created_at", "sender_kind", "agent_key", "body_col", "governance_status", "claim_level", "streaming_status")
    readonly_fields = ("body_col",)
    ordering = ("seq",)
    verbose_name_plural = "Messages"

    @admin.display(description="Body")
    def body_col(self, obj):
        return truncate(obj.body, 160)


class ThreadMessageInline(MessageInline):
    fk_name = "thread"


class ParticipantInline(ReadOnlyTabularInline):
    model = Participant
    fields = ("kind", "display_name", "client", "user", "last_read_at")
    verbose_name_plural = "Participants"


class ThreadParticipantInline(ReadOnlyTabularInline):
    model = ThreadParticipant
    fields = ("principal_kind", "principal_id", "role", "joined_at")
    verbose_name_plural = "Participants"


class MessageAttachmentInline(ReadOnlyTabularInline):
    model = MessageAttachment
    fields = ("order", "attachment_id", "created_at")
    verbose_name_plural = "Attachments"


class ArtifactInline(ReadOnlyTabularInline):
    model = Artifact
    fields = ("created_at", "type", "version", "disclosure_level", "governance_status", "pinned", "superseded_by")
    ordering = ("-created_at",)
    verbose_name_plural = "Artifacts"


class QuestionSuggestionInline(ReadOnlyTabularInline):
    model = QuestionSuggestion
    fk_name = "thread"
    fields = ("created_at", "target_dimension", "primary_text")
    ordering = ("-created_at",)
    verbose_name_plural = "Question suggestions"


class CoverageSnapshotInline(ReadOnlyTabularInline):
    model = CoverageSnapshot
    fields = ("dimension", "status", "evidence_message_id", "updated_at")
    verbose_name_plural = "Coverage"


class ThreadAttachmentInline(ReadOnlyTabularInline):
    model = Attachment
    fields = ("created_at", "filename", "status", "detected_mime", "bytes", "pre_nda")
    ordering = ("-created_at",)
    verbose_name_plural = "Uploaded files"


# ─────────────────────────────────────────────────────────────────────────────
# Thread (v6 container)
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Thread)
class ThreadAdmin(ItrixModelAdmin):
    list_display = (
        "short_id_col",
        "title_col",
        "context",
        "owner_kind",
        "current_state",
        "lead",
        "client",
        "questions_asked",
        "last_activity_at",
        "created_at",
    )
    list_display_links = ("short_id_col", "title_col")
    list_filter = ("context", "owner_kind", "current_state", "title_source", ("client", admin.EmptyFieldListFilter))
    search_fields = ("id", "title", "visitor_session", "lead__company", "lead__email", "client__email")
    raw_id_fields = ("lead", "client", "conversation")
    date_hierarchy = "created_at"
    ordering = ("-last_activity_at", "-created_at")
    readonly_fields = (
        "id",
        "owner_kind",
        "visitor_session",
        "state_at_creation",
        "current_state",
        "questions_asked",
        "last_activity_at",
        "claimed_at",
        "created_at",
        "updated_at",
        "conversation_link",
    )
    fieldsets = (
        (
            "Thread",
            {
                "fields": (
                    ("title", "title_source"),
                    ("context", "owner_kind"),
                    ("state_at_creation", "current_state"),
                    ("questions_asked", "last_activity_at"),
                    "id",
                )
            },
        ),
        (
            "Principals",
            {"fields": (("visitor_session",), ("client", "lead"), ("claimed_at",), ("conversation", "conversation_link"))},
        ),
        ("Retention", {"fields": (("retention_expires_at",),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [
        ThreadParticipantInline,
        ThreadMessageInline,
        ArtifactInline,
        CoverageSnapshotInline,
        QuestionSuggestionInline,
        ThreadAttachmentInline,
    ]

    @admin.display(description="Thread", ordering="id")
    def short_id_col(self, obj):
        return short_id(obj.id)

    @admin.display(description="Title", ordering="title")
    def title_col(self, obj):
        return truncate(obj.title, 60)

    @admin.display(description="Legacy conversation")
    def conversation_link(self, obj):
        return link_to(obj.conversation)


@admin.register(ThreadParticipant)
class ThreadParticipantAdmin(ReadOnlyAdmin):
    list_display = ("thread", "principal_kind", "principal_id", "role", "joined_at")
    list_filter = ("principal_kind", "role")
    search_fields = ("principal_id", "thread__id", "thread__title")
    ordering = ("-joined_at",)


# ─────────────────────────────────────────────────────────────────────────────
# Conversation (legacy container)
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Conversation)
class ConversationAdmin(ItrixModelAdmin):
    list_display = ("short_id_col", "title_col", "context", "lead", "client", "is_active", "last_message_at", "created_at")
    list_display_links = ("short_id_col", "title_col")
    list_filter = ("context", "is_active")
    search_fields = ("id", "title", "lead__company", "lead__email", "client__email", "review_session_id")
    raw_id_fields = ("lead", "client")
    date_hierarchy = "created_at"
    ordering = ("-last_message_at", "-created_at")
    readonly_fields = ("id", "review_session_id", "last_message_at", "created_at", "updated_at", "thread_link")
    fieldsets = (
        (None, {"fields": (("title", "context"), ("lead", "client"), ("is_active", "last_message_at"), ("review_session_id", "id"), "thread_link")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [ParticipantInline, MessageInline]

    @admin.display(description="Conversation", ordering="id")
    def short_id_col(self, obj):
        return short_id(obj.id)

    @admin.display(description="Title", ordering="title")
    def title_col(self, obj):
        return truncate(obj.title, 60)

    @admin.display(description="Thread")
    def thread_link(self, obj):
        return link_to(getattr(obj, "thread", None))


@admin.register(Participant)
class ParticipantAdmin(ReadOnlyAdmin):
    list_display = ("conversation", "kind", "display_name", "client", "user", "last_read_at")
    list_filter = ("kind",)
    search_fields = ("display_name", "conversation__id", "client__email", "user__email")


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Message)
class MessageAdmin(AppendOnlyAdmin):
    list_display = (
        "created_at",
        "seq",
        "sender_col",
        "body_col",
        "governance_col",
        "claim_col",
        "streaming_col",
        "thread",
        "conversation",
    )
    list_filter = ("sender_kind", "governance_status", "streaming_status", "claim_level", "agent_key")
    search_fields = ("body", "agent_key", "agent_run_id", "conversation__id", "thread__id", "thread__title")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("thread", "conversation")
    readonly_fields = ("meta_pretty", "cited_chunk_ids_pretty", "summary_of_pretty")
    fieldsets = (
        (
            "Turn",
            {
                "fields": (
                    ("conversation", "thread", "seq"),
                    ("sender_kind", "sender_client", "sender_user", "agent_key"),
                    "body",
                    "context_note",
                    "id",
                )
            },
        ),
        (
            "Governance",
            {"fields": (("governance_status", "claim_level", "streaming_status"), "cited_chunk_ids_pretty", "agent_run_id")},
        ),
        ("Meta", {"fields": ("summary_of_pretty", "meta_pretty"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [MessageAttachmentInline]

    @admin.display(description="Sender", ordering="sender_kind")
    def sender_col(self, obj):
        label = (obj.agent_key or "agent") if obj.sender_kind == "agent" else obj.sender_kind
        return badge(label, {"agent": "primary", "visitor": "info", "client": "info", "team": "success", "system": "muted"}.get(obj.sender_kind, "muted"))

    @admin.display(description="Body")
    def body_col(self, obj):
        return truncate(obj.body, 110)

    @admin.display(description="Governance", ordering="governance_status")
    def governance_col(self, obj):
        return badge(obj.governance_status)

    @admin.display(description="Claim", ordering="claim_level")
    def claim_col(self, obj):
        return claim_level_badge(obj.claim_level)

    @admin.display(description="Stream", ordering="streaming_status")
    def streaming_col(self, obj):
        return badge(obj.streaming_status)

    @admin.display(description="Meta")
    def meta_pretty(self, obj):
        return pretty_json(obj.meta)

    @admin.display(description="Cited chunk ids")
    def cited_chunk_ids_pretty(self, obj):
        return pretty_json(obj.cited_chunk_ids)

    @admin.display(description="Summary of")
    def summary_of_pretty(self, obj):
        return pretty_json(obj.summary_of)


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "message", "attachment_id", "order")
    search_fields = ("attachment_id", "message__id")
    ordering = ("-created_at",)
