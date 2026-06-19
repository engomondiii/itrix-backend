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
    """
    Dashboard send payload (camelCase). A send is either lead-scoped (``leadId``) or
    ad-hoc by recipient (``to``); at least one is required. A future ``scheduledAt``
    queues the send instead of delivering it inline.
    """

    leadId = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    to = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    subject = serializers.CharField()
    body = serializers.CharField()
    templateId = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    # The dashboard sends CC as a single string (one address or a comma/semicolon
    # separated list); we normalise it to a list for storage.
    cc = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    scheduledAt = serializers.DateTimeField(required=False, allow_null=True)
    attachments = serializers.ListField(child=serializers.CharField(), required=False, default=list)

    def validate_cc(self, value):
        if not value:
            return []
        return [addr.strip() for addr in value.replace(";", ",").split(",") if addr.strip()]

    def validate(self, attrs):
        if not attrs.get("leadId") and not attrs.get("to"):
            raise serializers.ValidationError("Provide either 'leadId' or 'to'.")
        return attrs
