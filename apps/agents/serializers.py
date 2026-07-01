"""Agent serializers — the run request/response + AgentRun audit shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.agents.models import AgentRun


class AgentRunSerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at", read_only=True)
    agentKey = serializers.CharField(source="agent_key", read_only=True)
    leadId = serializers.CharField(source="lead_id", read_only=True)
    usedAi = serializers.BooleanField(source="used_ai", read_only=True)
    governanceStatus = serializers.CharField(source="governance_status", read_only=True)
    claimLevel = serializers.IntegerField(source="claim_level", read_only=True)
    durationMs = serializers.IntegerField(source="duration_ms", read_only=True)

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "agentKey",
            "leadId",
            "status",
            "usedAi",
            "governanceStatus",
            "claimLevel",
            "output",
            "chunk_ids",
            "durationMs",
            "at",
        ]
        read_only_fields = fields


class AgentRunRequestSerializer(serializers.Serializer):
    """Body for ``POST agents/{key}/run/`` (team-guarded, behind ENABLE_AGENTS)."""

    lead_id = serializers.UUIDField(required=False)
    context_label = serializers.CharField(required=False, default="diagnosis")
    message = serializers.CharField(required=False, allow_blank=True, default="")
