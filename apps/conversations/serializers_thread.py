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
    canContinue = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
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
            "canContinue",
            "attachments",
            "at",
        ]
        read_only_fields = fields

    def get_underReview(self, obj) -> bool:
        return not obj.is_deliverable

    def get_canContinue(self, obj) -> bool:
        """Whether this assistant turn ended because the model hit its output ceiling."""
        if obj.sender_kind != "agent" or not obj.is_deliverable:
            return False
        return bool((obj.meta or {}).get("can_continue", False))

    def get_attachments(self, obj) -> list[dict]:
        """Safe attachment metadata for files sent WITH this visitor turn.

        The link table deliberately stores plain ids so conversations has no hard app
        dependency. Resolve them lazily and expose only visitor-safe display fields —
        never blob keys, hashes, risk flags, scanner detail or uploader ids.
        """
        if obj.sender_kind not in ("visitor", "client"):
            return []
        try:
            links = list(obj.attachment_links.all().order_by("order", "created_at"))
            wanted = [str(link.attachment_id) for link in links]
            if not wanted:
                return []

            from apps.attachments.models import Attachment

            rows = Attachment.objects.filter(
                id__in=wanted,
                thread_id=obj.thread_id,
                deleted_at__isnull=True,
            ).only("id", "filename", "bytes", "detected_mime")
            by_id = {str(row.id): row for row in rows}
            return [
                {
                    "attachmentId": str(by_id[attachment_id].id),
                    "filename": by_id[attachment_id].filename,
                    "sizeBytes": int(by_id[attachment_id].bytes or 0),
                    "detectedType": by_id[attachment_id].detected_mime or "",
                }
                for attachment_id in wanted
                if attachment_id in by_id
            ]
        except Exception:  # noqa: BLE001 - attachments are optional/flag-gated
            return []

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
    engagement = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = ["threadId", "title", "context", "lastActivityAt", "turns", "shell", "engagement"]
        read_only_fields = fields

    def get_turns(self, obj):
        messages = Message.objects.filter(thread=obj).order_by("seq", "created_at")
        return ThreadTurnSerializer(messages, many=True).data

    def get_engagement(self, obj):
        from apps.conversations.services import engagement_state

        return engagement_state.public_state(obj)

    def get_shell(self, obj):
        """
        The shell contract for this thread.

        ``left_rail`` / ``right_rail`` are ABSENT — the rails contract was retired in
        Phase 3. ``sidebar_sections`` and ``conversation_header`` replace them.
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

# ─────────────────────────────────────────────────────────────────────────────
# THE RAILS CONTRACT IS RETIRED (Backend v6.0 §Phase 3, §3.1)
# ─────────────────────────────────────────────────────────────────────────────
# ``left_rail`` and ``right_rail`` were emitted as ``[]`` / ``null`` deprecation stubs
# through Phases 1-2, giving both frontends a full release to migrate. Phase 3 removes
# them.
#
# They are now ABSENT from every payload, and a client that SENDS them receives 400 —
# see ``reject_rail_fields`` below. Silently accepting a field we no longer honour would
# leave a frontend believing it still controls something it does not.
RETIRED_FIELDS = ("left_rail", "right_rail", "leftRail", "rightRail")


class RailFieldsRetired(Exception):
    """Raised when a request carries a retired rails field. Maps to HTTP 400."""


def reject_rail_fields(data) -> None:
    """
    Refuse a request that still speaks the rails contract.

    Explicit rather than ignored: a 400 naming the field tells the frontend author what
    to change, where silence would let a stale client ship believing it still works.
    """
    if not isinstance(data, dict):
        return
    present = [field for field in RETIRED_FIELDS if field in data]
    if present:
        # v7.1 PHASE 3: the replacement named here CHANGED. This message used to point at
        # `sidebar_sections`, which Phase 3 removed — so the guidance sent to a frontend
        # author was telling them to migrate onto a field that no longer exists. An error
        # message is part of the contract, and a stale one costs the support round trip it
        # was written to avoid.
        raise RailFieldsRetired(
            f"The rails contract was retired in Backend v6.0. "
            f"Remove {', '.join(present)} and read `conversation_rail_sections`, "
            f"`content_pane_sections` and `conversation_header` from the shell contract "
            f"instead. (`sidebar_sections` was the v6.0 alias and was removed in v7.1.)"
        )
