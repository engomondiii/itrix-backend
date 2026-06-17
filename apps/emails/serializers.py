"""Email serializers."""

from __future__ import annotations

from rest_framework import serializers

from apps.emails.models import EmailLog


class EmailLogSerializer(serializers.ModelSerializer):
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    leadId = serializers.CharField(source="lead_id", read_only=True)

    class Meta:
        model = EmailLog
        fields = [
            "id", "kind", "to_email", "from_email", "subject", "body",
            "status", "error", "leadId", "createdAt",
        ]
        read_only_fields = fields


class SendEmailSerializer(serializers.Serializer):
    lead_id = serializers.CharField()
    subject = serializers.CharField()
    body = serializers.CharField()
