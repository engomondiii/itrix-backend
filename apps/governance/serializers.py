"""Governance serializers — Claim-Card CRUD + approval-queue + audit shapes."""

from __future__ import annotations

from rest_framework import serializers

from apps.governance.models import ApprovalRequest, ClaimCard


class ClaimCardSerializer(serializers.ModelSerializer):
    approvedWording = serializers.CharField(source="approved_wording")
    claimLevel = serializers.IntegerField(source="claim_level")
    isActive = serializers.BooleanField(source="is_active", required=False)
    ownerName = serializers.SerializerMethodField()

    class Meta:
        model = ClaimCard
        fields = [
            "id",
            "key",
            "title",
            "approvedWording",
            "claimLevel",
            "isActive",
            "ownerName",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "ownerName", "created_at", "updated_at"]

    def get_ownerName(self, obj) -> str | None:
        return obj.owner.display_name if obj.owner else None


class ApprovalRequestSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    # The thread this draft is delivered into. Surface 2 links back to it from the
    # approval queue and the governance audit, so a reviewer can read the context
    # before approving.
    conversationId = serializers.CharField(source="conversation_id", read_only=True)
    agentKey = serializers.CharField(source="agent_key", read_only=True)
    claimLevel = serializers.IntegerField(source="claim_level", read_only=True)
    draftBody = serializers.CharField(source="draft_body", read_only=True)
    finalBody = serializers.CharField(source="final_body", read_only=True)
    citedChunkIds = serializers.ListField(source="cited_chunk_ids", read_only=True)
    requiresSecondApprover = serializers.BooleanField(source="requires_second_approver", read_only=True)
    firstApprover = serializers.SerializerMethodField()
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "leadId",
            "conversationId",
            "agentKey",
            "claimLevel",
            "draftBody",
            "finalBody",
            "citedChunkIds",
            "status",
            "reason",
            "requiresSecondApprover",
            "firstApprover",
            "at",
        ]
        read_only_fields = fields

    def get_firstApprover(self, obj) -> str | None:
        return obj.first_approver.display_name if obj.first_approver else None


class ApprovalActionSerializer(serializers.Serializer):
    """Body for approve/edit/reject actions."""

    body = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
