"""Evaluation serializers — emit the dashboard's Evaluation shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.evaluations.models import Evaluation


class EvaluationSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Evaluation
        fields = [
            "id", "leadId", "leadName", "company", "pkg", "status",
            "kpis", "scope", "fee", "timeline", "createdAt", "updatedAt",
        ]
        read_only_fields = ["id", "leadId", "createdAt", "updatedAt"]
        extra_kwargs = {
            "scope": {"required": False, "allow_blank": True},
            "fee": {"required": False, "allow_blank": True},
            "timeline": {"required": False, "allow_blank": True},
        }


class CreateEvaluationSerializer(serializers.Serializer):
    lead_id = serializers.CharField()
