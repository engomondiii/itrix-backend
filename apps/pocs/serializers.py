"""PoC serializers — emit the dashboard's PoC shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.pocs.models import PoC


class PoCSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = PoC
        fields = [
            "id", "leadId", "leadName", "company", "status",
            "milestones", "kpis", "risks", "createdAt", "updatedAt",
        ]
        read_only_fields = ["id", "leadId", "createdAt", "updatedAt"]


class CreatePoCSerializer(serializers.Serializer):
    lead_id = serializers.CharField()
