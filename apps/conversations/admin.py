"""Admin for conversations, messages, and participants."""

from __future__ import annotations

from django.contrib import admin

from apps.conversations.models import Conversation, Message, Participant


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("sender_kind", "agent_key", "body", "governance_status", "claim_level", "created_at")
    can_delete = False


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0
    readonly_fields = ("kind", "client", "user", "display_name", "last_read_at")
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "context", "lead", "client", "is_active", "last_message_at", "created_at")
    list_filter = ("context", "is_active")
    search_fields = ("id", "lead__id", "client__id", "review_session_id", "title")
    readonly_fields = ("id", "created_at", "updated_at", "last_message_at")
    inlines = [ParticipantInline, MessageInline]
    date_hierarchy = "created_at"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender_kind", "agent_key", "governance_status", "claim_level", "created_at")
    list_filter = ("sender_kind", "governance_status")
    search_fields = ("conversation__id", "body", "agent_key")
    readonly_fields = tuple(f.name for f in Message._meta.fields)


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "kind", "display_name", "last_read_at")
    list_filter = ("kind",)
