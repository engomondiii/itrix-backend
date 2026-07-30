"""Client serializers — invite claim I/O and the client identity shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.clients.models import Client


class ClientIdentitySerializer(serializers.ModelSerializer):
    """The client profile the portal renders (camelCase; Surface 1 client plane)."""

    leadId = serializers.CharField(source="lead_id", read_only=True)
    fullName = serializers.CharField(source="full_name", allow_blank=True)
    ndaSigned = serializers.BooleanField(source="nda_signed", read_only=True)
    # v7.2 — a fact about the holder's OWN address, so it is theirs to see. It is not a
    # disclosure about anybody else. `itrix-web` reads a MISSING key as "unknown" rather than
    # as unconfirmed, which is why this is the only place it can come from.
    emailVerified = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id",
            "leadId",
            "email",
            "fullName",
            "organization",
            "role",
            "ndaSigned",
            "emailVerified",
        ]
        read_only_fields = ["id", "leadId", "email", "ndaSigned", "emailVerified"]

    def get_emailVerified(self, obj) -> bool:
        return getattr(obj, "email_verified_at", None) is not None


class InviteClaimRequestSerializer(serializers.Serializer):
    """Body for ``POST accounts/invite/{token}/claim/``."""

    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    organization = serializers.CharField(required=False, allow_blank=True, default="")
    role = serializers.CharField(required=False, allow_blank=True, default="")
    # v7.2 — the instrument versions the visitor was SHOWN travel with the claim, and
    # `claim_invite()` writes the record inside the transaction that creates the Client
    # (R62). The surface used to POST them separately to `portal/legal/assent/` first, which
    # produced a SECOND record because the backend has recorded one in-transaction since
    # v7.1 Phase 3.
    assent = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class InviteClaimResponseSerializer(serializers.Serializer):
    """Response for a successful claim (client profile + password-set flag + tokens)."""

    client = ClientIdentitySerializer()
    requiresPasswordSet = serializers.BooleanField()


class PasswordSetRequestSerializer(serializers.Serializer):
    """Body for ``POST client/auth/password/set/`` (first-time / reset)."""

    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=10)
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — client-plane auth + portal payload serializers
# ─────────────────────────────────────────────────────────────────────────────
class ClientLoginRequestSerializer(serializers.Serializer):
    """Body for POST client/auth/login/."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class ClientTokenRefreshRequestSerializer(serializers.Serializer):
    """Body for POST client/auth/token/refresh/."""

    refresh = serializers.CharField()


class PortalOverviewSerializer(serializers.Serializer):
    """The personalized portal workspace payload (PortalOverview)."""

    client = ClientIdentitySerializer()
    stage = serializers.CharField()            # journey state (client-facing label)
    unreadMessages = serializers.IntegerField()
    briefingAvailable = serializers.BooleanField()
    nextSteps = serializers.ListField(child=serializers.CharField())
    ndaSigned = serializers.BooleanField()
    lastUpdated = serializers.DateTimeField(allow_null=True)


class PortalDocumentSerializer(serializers.Serializer):
    title = serializers.CharField()
    disclosure = serializers.CharField()
    href = serializers.CharField(allow_blank=True)
    locked = serializers.BooleanField()


class PortalDataRoomSerializer(serializers.Serializer):
    """PortalDataRoom — NDA-aware document listing."""

    ndaSigned = serializers.BooleanField()
    documents = PortalDocumentSerializer(many=True)


class PortalEvaluationSerializer(serializers.Serializer):
    exists = serializers.BooleanField()
    stage = serializers.CharField(allow_blank=True)
    kpis = serializers.ListField(child=serializers.DictField(), default=list)
    reportHref = serializers.CharField(allow_blank=True)


class PortalPoCSerializer(serializers.Serializer):
    exists = serializers.BooleanField()
    stage = serializers.CharField(allow_blank=True)
    milestones = serializers.ListField(child=serializers.DictField(), default=list)
    successCriteria = serializers.ListField(child=serializers.DictField(), default=list)


class PortalSettingsSerializer(serializers.Serializer):
    """GET/PATCH portal/settings/ — client profile + notification prefs."""

    fullName = serializers.CharField(source="full_name", allow_blank=True, required=False)
    organization = serializers.CharField(allow_blank=True, required=False)
    role = serializers.CharField(allow_blank=True, required=False)
    email = serializers.EmailField(read_only=True)
