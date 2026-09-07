"""Payload validation for the existing ASTOP entitlement lifecycle."""

from rest_framework import serializers


class ASTOPEntitlementLifecycleSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["activate", "expire", "revoke"])
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")

    def validate(self, attrs):
        action = attrs["action"]
        if action != "activate" and "expires_at" in attrs:
            raise serializers.ValidationError(
                {"expires_at": "An explicit expiry may only be supplied when activating an entitlement."}
            )
        return attrs
