"""NDA serializers — emit the dashboard's NDARecord shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.nda.models import NDARecord


class NDARecordSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    requestedAt = serializers.DateTimeField(source="requested_at", read_only=True)
    signedAt = serializers.DateTimeField(source="signed_at", read_only=True)

    class Meta:
        model = NDARecord
        fields = [
            "id", "leadId", "leadName", "company", "status",
            "checklist", "requestedAt", "signedAt",
        ]
        read_only_fields = ["id", "leadId", "requestedAt", "signedAt"]


class ChecklistUpdateSerializer(serializers.Serializer):
    checklist = serializers.ListField(child=serializers.DictField(), required=True)
