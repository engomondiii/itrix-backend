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
    attachments = serializers.SerializerMethodField()
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
            "attachments",
            "at",
        ]
        read_only_fields = fields

    def get_underReview(self, obj) -> bool:
        return not obj.is_deliverable

    def get_body(self, obj) -> str:
        # Never leak held/blocked content to a client-facing serializer.
        return obj.body if obj.is_deliverable else ""

    def get_attachments(self, obj):
        """
        The files sent with this turn, in the shape the thread renders
        (portal chips + the anonymous transcript alike). Lazy import and
        broad except: `attachments` is a flag-gated app, and a message must
        render even when it is off or a link points at a purged file.
        """
        links = getattr(obj, "attachment_links", None)
        if links is None:
            return []
        ids = [link.attachment_id for link in links.all()]
        if not ids:
            return []
        try:
            from apps.attachments.models import Attachment

            rows = Attachment.objects.filter(id__in=ids)
            return [
                {
                    "attachmentId": str(a.id),
                    "filename": a.filename,
                    "sizeBytes": a.bytes,
                    "downloadable": a.is_downloadable,
                }
                for a in rows
                if not a.is_deleted
            ]
        except Exception:  # noqa: BLE001
            return []


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
    # The spine's id, so the workspace composer can stage attachments against the
    # thread that owns them (attachments are thread-scoped). Null for the shipped
    # conversations that predate the spine; the portal send creates it on demand.
    threadId = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "context", "title", "threadId", "messages"]
        read_only_fields = fields

    def get_threadId(self, obj):  # noqa: N802 — camelCase is the client-plane contract
        thread = getattr(obj, "thread", None)
        return str(thread.id) if thread is not None else None

    def get_messages(self, obj):
        from apps.conversations.services.history import deliverable_messages

        return MessageSerializer(deliverable_messages(obj), many=True).data


# ── Team-plane variants ───────────────────────────────────────────────────────
# The serializers above are consumed by the CLIENT portal, so they must never carry
# internal identifiers. The team console needs the owning lead in order to link a
# thread back to its CRM record — so it gets its own shapes, used only behind
# team-JWT views.


class TeamConversationSummarySerializer(ConversationSummarySerializer):
    """
    Console conversation row — adds the owning lead and the thread (team plane only).

    ── THE MAPPING LINK (2026-08-12) ────────────────────────────────────────────
    Conversation and Thread are separate models, and the console had no way to get from
    one to the other: this row carried a conversation id, while every row-level cockpit
    resource — the thread board, thread detail, coverage, guard hits — is keyed by
    THREAD. An operator reading a conversation could not open the board row for it
    without a lookup that no endpoint offered, so the two halves of the same
    conversation were reachable only by coincidence.

    Null for the shipped review and client-page conversations that predate the spine.
    Null is the honest answer there — those genuinely have no thread — and it is
    distinguishable from "not sent", which an omitted field would not be.
    """

    leadId = serializers.CharField(source="lead_id", read_only=True)
    threadId = serializers.SerializerMethodField()

    class Meta(ConversationSummarySerializer.Meta):
        fields = [*ConversationSummarySerializer.Meta.fields, "leadId", "threadId"]
        read_only_fields = fields

    def get_threadId(self, obj):  # noqa: N802 — camelCase is the wire contract
        thread = getattr(obj, "thread", None)
        return str(thread.id) if thread is not None else None


class TeamConversationThreadSerializer(ConversationThreadSerializer):
    """Console thread — adds the owning lead (team plane only)."""

    leadId = serializers.CharField(source="lead_id", read_only=True)

    class Meta(ConversationThreadSerializer.Meta):
        fields = [*ConversationThreadSerializer.Meta.fields, "leadId"]
        read_only_fields = fields
