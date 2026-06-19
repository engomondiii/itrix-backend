"""PoC serializers — emit the dashboard's PoC shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.pocs.models import PoC


class PoCSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    durationWeeks = serializers.IntegerField(
        source="duration_weeks", required=False, allow_null=True
    )
    successMetrics = serializers.CharField(
        source="success_metrics", required=False, allow_blank=True
    )
    startDate = serializers.DateField(
        source="start_date", required=False, allow_null=True
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = PoC
        fields = [
            "id", "leadId", "leadName", "company", "status",
            "milestones", "kpis", "risks",
            "scope", "durationWeeks", "successMetrics", "startDate",
            "createdAt", "updatedAt",
        ]
        read_only_fields = ["id", "leadId", "createdAt", "updatedAt"]
        extra_kwargs = {"scope": {"required": False, "allow_blank": True}}


class CreatePoCSerializer(serializers.Serializer):
    lead_id = serializers.CharField()
