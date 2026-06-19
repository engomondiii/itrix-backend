"""Follow-up serializers — emit the dashboard's FollowUpTask shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.follow_up.models import FollowUpTask


class FollowUpTaskSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    owner = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    dueAt = serializers.DateTimeField(source="due_at", read_only=True)
    snoozedUntil = serializers.DateTimeField(source="snoozed_until", read_only=True)

    class Meta:
        model = FollowUpTask
        fields = [
            "id", "leadId", "leadName", "company", "tier", "owner",
            "createdAt", "dueAt", "status", "snoozedUntil", "note",
        ]
        read_only_fields = fields

    def get_owner(self, obj) -> str | None:
        return obj.owner.display_name if obj.owner else None


class SnoozeSerializer(serializers.Serializer):
    hours = serializers.IntegerField(required=False, default=24, min_value=1, max_value=720)


class RescheduleSerializer(serializers.Serializer):
    dueAt = serializers.DateTimeField()
