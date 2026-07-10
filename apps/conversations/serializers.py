"""
Conversation serializers.

Emit the camelCase shapes Surface 1's portal consumes (PortalConversation / PortalThread
/ ChatMessage). Client-facing serializers only ever surface deliverable messages; held
drafts are represented by an ``underReview`` flag, never their body.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.conversations.models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    """A single chat message (client-facing)."""

    senderKind = serializers.CharField(source="sender_kind", read_only=True)
    agentKey = serializers.CharField(source="agent_key", read_only=True)
    citedChunkIds = serializers.ListField(source="cited_chunk_ids", read_only=True)
    governanceStatus = serializers.CharField(source="governance_status", read_only=True)
    underReview = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "senderKind",
            "agentKey",
            "body",
            "citedChunkIds",
            "governanceStatus",
            "underReview",
            "at",
        ]
        read_only_fields = fields

    def get_underReview(self, obj) -> bool:
        return not obj.is_deliverable

    def get_body(self, obj) -> str:
        # Never leak held/blocked content to a client-facing serializer.
        return obj.body if obj.is_deliverable else ""


class ConversationSummarySerializer(serializers.ModelSerializer):
    """A row in the portal conversation list (PortalConversation)."""

    lastMessageAt = serializers.DateTimeField(source="last_message_at", read_only=True)
    unreadCount = serializers.SerializerMethodField()
    lastPreview = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "context", "title", "lastMessageAt", "unreadCount", "lastPreview"]
        read_only_fields = fields

    def get_unreadCount(self, obj) -> int:
        client = self.context.get("client")
        from apps.conversations.services.history import unread_count

        return unread_count(obj, client=client)

    def get_lastPreview(self, obj) -> str:
        from apps.conversations.services.history import deliverable_messages

        last = deliverable_messages(obj).last()
        if not last:
            return ""
        return (last.body[:120] + "…") if len(last.body) > 120 else last.body


class ConversationThreadSerializer(serializers.ModelSerializer):
    """A full thread with its deliverable messages (PortalThread)."""

    messages = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "context", "title", "messages"]
        read_only_fields = fields

    def get_messages(self, obj):
        from apps.conversations.services.history import deliverable_messages

        return MessageSerializer(deliverable_messages(obj), many=True).data


# ── Team-plane variants ───────────────────────────────────────────────────────
# The serializers above are consumed by the CLIENT portal, so they must never carry
# internal identifiers. The team console needs the owning lead in order to link a
# thread back to its CRM record — so it gets its own shapes, used only behind
# team-JWT views.


class TeamConversationSummarySerializer(ConversationSummarySerializer):
    """Console conversation row — adds the owning lead (team plane only)."""

    leadId = serializers.CharField(source="lead_id", read_only=True)

    class Meta(ConversationSummarySerializer.Meta):
        fields = [*ConversationSummarySerializer.Meta.fields, "leadId"]
        read_only_fields = fields


class TeamConversationThreadSerializer(ConversationThreadSerializer):
    """Console thread — adds the owning lead (team plane only)."""

    leadId = serializers.CharField(source="lead_id", read_only=True)

    class Meta(ConversationThreadSerializer.Meta):
        fields = [*ConversationThreadSerializer.Meta.fields, "leadId"]
        read_only_fields = fields
