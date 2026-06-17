"""AI Engine serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.ai_engine.models import GenerationLog


class GenerateResultRequestSerializer(serializers.Serializer):
    """Public body for ``ai/generate-result/`` (sent by the web result proxy)."""

    lead_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    session_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("lead_id") and not attrs.get("session_id"):
            raise serializers.ValidationError("Either lead_id or session_id is required.")
        return attrs


class GenerationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationLog
        fields = [
            "id",
            "lead",
            "review_session",
            "product_route",
            "used_ai",
            "chunk_count",
            "prohibited_removed",
            "quant_hedged",
            "ok",
            "error",
            "created_at",
        ]
        read_only_fields = fields
