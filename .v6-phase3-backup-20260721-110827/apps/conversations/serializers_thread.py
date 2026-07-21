"""
Thread serializers — PLANE-AWARE (Backend v6.0 §1.2).

Two shapes, and the difference between them is a security boundary rather than a
convenience:

    ThreadSummarySerializer / ThreadDetailSerializer   anonymous + client planes
    TeamThreadSerializer                               team plane only

── THE FIELD ALLOW-LIST (Architecture v2.6 §10.5) ───────────────────────────
The following must NOT appear in any payload on the anonymous or client plane, at any
state, in any turn, artifact or card:

    persona_id · pitch_room_id · tier · lead score · score breakdown
    license_out_probability · churn_risk · account_priority
    negotiation_posture · competitor_risk · objection_classification
    gate_decision · gate_decision_reason · internal notes · owner private fields
    coverage_map · question_budget_remaining · attachment_risk_flags
    retrieval_debug · chunk_ids_internal · stream_guard_hits

This is enforced by EXPLICIT ALLOW-LISTS below, not by remembering to exclude things.
An allow-list fails closed when a new field is added to the model; a deny-list fails
open, which is how internal fields leak.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.conversations.models import Message, Thread


class ThreadTurnSerializer(serializers.ModelSerializer):
    """One turn in the transcript (client-facing)."""

    senderKind = serializers.CharField(source="sender_kind", read_only=True)
    agentKey = serializers.CharField(source="agent_key", read_only=True)
    governanceStatus = serializers.CharField(source="governance_status", read_only=True)
    streamingStatus = serializers.CharField(source="streaming_status", read_only=True)
    contextNote = serializers.CharField(source="context_note", read_only=True)
    underReview = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "seq",
            "senderKind",
            "agentKey",
            "body",
            "governanceStatus",
            "streamingStatus",
            "contextNote",
            "underReview",
            "at",
        ]
        read_only_fields = fields

    def get_underReview(self, obj) -> bool:
        return not obj.is_deliverable

    def get_body(self, obj) -> str:
        """
        Never leak held, blocked or HALTED content.

        A halted message's partial text was discarded from the client on purpose. If it
        reappeared on a history fetch, the halt would have achieved nothing.
        """
        if obj.streaming_status == "halted":
            return ""
        return obj.body if obj.is_deliverable else ""


class ThreadSummarySerializer(serializers.ModelSerializer):
    """A row in the sidebar conversation list."""

    threadId = serializers.CharField(source="id", read_only=True)
    lastActivityAt = serializers.DateTimeField(source="last_activity_at", read_only=True)
    titleSource = serializers.CharField(source="title_source", read_only=True)

    class Meta:
        model = Thread
        # ALLOW-LIST. Note what is absent: lead, client, visitor_session, owner_kind.
        # A conversation list row needs a title and a timestamp, nothing more.
        fields = ["threadId", "title", "titleSource", "context", "lastActivityAt"]
        read_only_fields = fields


class ThreadDetailSerializer(serializers.ModelSerializer):
    """A thread with its transcript and its shell contract."""

    threadId = serializers.CharField(source="id", read_only=True)
    lastActivityAt = serializers.DateTimeField(source="last_activity_at", read_only=True)
    turns = serializers.SerializerMethodField()
    shell = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = ["threadId", "title", "context", "lastActivityAt", "turns", "shell"]
        read_only_fields = fields

    def get_turns(self, obj):
        messages = Message.objects.filter(thread=obj).order_by("seq", "created_at")
        return ThreadTurnSerializer(messages, many=True).data

    def get_shell(self, obj):
        """
        The shell contract for this thread.

        ``left_rail`` / ``right_rail`` are ABSENT here by design — see
        ``deprecated_rail_stub()`` for the one-release compatibility shim, which lives
        on the journey payload rather than being baked into this shape.
        """
        from apps.journey.services import shell

        if obj.lead_id:
            return shell.for_subject(obj.lead, thread=obj)
        return shell.for_anonymous_thread(obj)


class TeamThreadSerializer(serializers.ModelSerializer):
    """
    TEAM PLANE. Adds the owning subject so the console can link a thread to its CRM
    record. Never mounted on a client-facing route.
    """

    threadId = serializers.CharField(source="id", read_only=True)
    leadId = serializers.CharField(source="lead_id", read_only=True)
    clientId = serializers.CharField(source="client_id", read_only=True)
    ownerKind = serializers.CharField(source="owner_kind", read_only=True)
    visitorSession = serializers.CharField(source="visitor_session", read_only=True)
    lastActivityAt = serializers.DateTimeField(source="last_activity_at", read_only=True)
    claimedAt = serializers.DateTimeField(source="claimed_at", read_only=True)
    retentionExpiresAt = serializers.DateTimeField(source="retention_expires_at", read_only=True)
    turnCount = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = [
            "threadId",
            "title",
            "context",
            "ownerKind",
            "leadId",
            "clientId",
            "visitorSession",
            "lastActivityAt",
            "claimedAt",
            "retentionExpiresAt",
            "turnCount",
        ]
        read_only_fields = fields

    def get_turnCount(self, obj) -> int:
        return Message.objects.filter(thread=obj).count()


class TurnSubmitSerializer(serializers.Serializer):
    """
    Body for ``POST threads/{id}/turns/``.

    NO ``max_length`` on ``body``. There is no user-facing character limit (R28); the
    server safety cap lives in ``validate_message_length`` and returns a specific,
    recoverable 413 rather than a validation error that discards what they wrote.
    """

    body = serializers.CharField(allow_blank=True, trim_whitespace=False)
    attachment_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class ThreadCreateSerializer(serializers.Serializer):
    """Body for ``POST threads/``. Everything optional — a bare POST is valid."""

    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    example_key = serializers.CharField(required=False, allow_blank=True)
    attachment_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )


class ThreadRenameSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)


def deprecated_rail_stub() -> dict:
    """
    The one-release compatibility shim for the retired rails contract.

    Backend v6.0 §3.1: ``left_rail`` and ``right_rail`` are emitted as ``[]`` / ``null``
    with a deprecation header for ONE release; after that they are absent and a client
    that sends them receives 400.

    Emitting empty rather than omitting is deliberate: a v4.0 frontend that reads
    ``payload.left_rail.map(...)`` keeps working (it maps an empty list) instead of
    crashing on undefined during the migration window.
    """
    return {"left_rail": [], "right_rail": None}
