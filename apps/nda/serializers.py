"""NDA serializers — emit the dashboard's NDARecord / NDAListItem shapes."""

from __future__ import annotations

from rest_framework import serializers

from apps.nda.models import NDARecord


class NDAListSerializer(serializers.ModelSerializer):
    """The dashboard's ``NDAListItem`` — every field except the heavy ``body``."""

    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    docType = serializers.CharField(source="doc_type")
    signerName = serializers.CharField(source="signer_name")
    signerEmail = serializers.CharField(source="signer_email")
    declineReason = serializers.CharField(source="decline_reason")
    requestedAt = serializers.DateTimeField(source="requested_at", read_only=True)
    sentAt = serializers.DateTimeField(source="sent_at", read_only=True)
    signedAt = serializers.DateTimeField(source="signed_at", read_only=True)

    class Meta:
        model = NDARecord
        fields = [
            "id", "leadId", "leadName", "company", "status", "checklist",
            "docType", "signerName", "signerEmail",
            "requestedAt", "sentAt", "signedAt", "declineReason",
        ]
        read_only_fields = ["id", "leadId", "requestedAt", "sentAt", "signedAt"]


class NDARecordSerializer(NDAListSerializer):
    """The dashboard's full ``NDARecord`` — list fields plus the document ``body``."""

    class Meta(NDAListSerializer.Meta):
        fields = NDAListSerializer.Meta.fields + ["body"]


class ChecklistUpdateSerializer(serializers.Serializer):
    checklist = serializers.ListField(child=serializers.DictField(), required=True)
