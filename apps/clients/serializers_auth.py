"""
Request bodies for the v7.2 authentication surface.

── WHAT IS NOT VALIDATED HERE, AND WHY ─────────────────────────────────────
Nothing in this module rejects an address for EXISTING. A serializer that raised
"this email is already in use" would be the enumeration oracle every string in
Playbook v1.9 Part XVIII is written to avoid, and DRF would render it as a field error
with a 400 — which is exactly the distinguishable response the collapse in the view
exists to prevent (R64).

Uniqueness is enforced by the database constraint and handled by the registration
service, which notifies the holder rather than the requester.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.clients.password_policy import min_length as _min_length
from apps.clients.password_policy import validate_client_password




class AssentEntrySerializer(serializers.Serializer):
    """One instrument the visitor was shown."""

    slug = serializers.CharField()
    version = serializers.CharField(allow_blank=True, required=False, default="")
    effective = serializers.CharField(allow_blank=True, required=False, default="")


class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    fullName = serializers.CharField(source="full_name", allow_blank=True, required=False, default="")
    organization = serializers.CharField(allow_blank=True, required=False, default="")
    role = serializers.CharField(allow_blank=True, required=False, default="")
    # The versions the visitor was SHOWN. Required: an account without a recorded basis is
    # the state §19.10 exists to prevent, and refusing here names nothing about any address.
    assent = AssentEntrySerializer(many=True)

    def validate_password(self, value: str) -> str:
        try:
            return validate_client_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc

    def validate_assent(self, value):
        if not value:
            raise serializers.ValidationError("Assent is required.")
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_password(self, value: str) -> str:
        try:
            return validate_client_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc


class PasswordChangeSerializer(serializers.Serializer):
    currentPassword = serializers.CharField(source="current_password", write_only=True)
    newPassword = serializers.CharField(source="new_password", write_only=True)

    def validate_newPassword(self, value: str) -> str:
        try:
            return validate_client_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc


class VerifyEmailConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()


class VerifyEmailResendSerializer(serializers.Serializer):
    # Optional: an authenticated client does not need to name an address at all.
    email = serializers.EmailField(required=False, allow_blank=True)
