"""
Attachment serializers — PLANE-AWARE (Backend v6.0 §1.2).

    plane-aware; RISK FLAGS ARE TEAM-ONLY

``attachment_risk_flags`` is on the §10.5 list of fields that must not appear in any
payload on the anonymous or client plane, at any state. It appears in
``TeamAttachmentSerializer`` and nowhere else.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.attachments.models import Attachment


class AttachmentSerializer(serializers.ModelSerializer):
    """
    VISITOR-FACING. Status is text plus a note — never a raw risk signal.

    ``visitorNote`` carries the honest message for a file we could not read. §13.4:
    never call an accepted file a failure.
    """

    attachmentId = serializers.CharField(source="id", read_only=True)
    detectedType = serializers.CharField(source="detected_mime", read_only=True)
    sizeBytes = serializers.IntegerField(source="bytes", read_only=True)
    visitorNote = serializers.CharField(source="visitor_note", read_only=True)
    isReadable = serializers.BooleanField(source="is_readable", read_only=True)
    at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Attachment
        # ALLOW-LIST. Absent by design: risk_flags, blob_key, sha256, uploaded_by_id,
        # pre_nda, retention_expires_at.
        fields = [
            "attachmentId", "filename", "detectedType", "sizeBytes",
            "status", "visitorNote", "isReadable", "at",
        ]
        read_only_fields = fields


class TeamAttachmentSerializer(serializers.ModelSerializer):
    """TEAM PLANE ONLY. Carries the risk flags and the retention state."""

    attachmentId = serializers.CharField(source="id", read_only=True)
    threadId = serializers.CharField(source="thread_id", read_only=True)
    declaredType = serializers.CharField(source="declared_mime", read_only=True)
    detectedType = serializers.CharField(source="detected_mime", read_only=True)
    sizeBytes = serializers.IntegerField(source="bytes", read_only=True)
    riskFlags = serializers.ListField(source="risk_flags", read_only=True)
    preNda = serializers.BooleanField(source="pre_nda", read_only=True)
    retentionExpiresAt = serializers.DateTimeField(source="retention_expires_at", read_only=True)
    scanVerdict = serializers.SerializerMethodField()
    extraction = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "attachmentId", "threadId", "filename", "declaredType", "detectedType",
            "sizeBytes", "sha256", "status", "riskFlags", "preNda",
            "retentionExpiresAt", "scanVerdict", "extraction",
        ]
        read_only_fields = fields

    def get_scanVerdict(self, obj) -> str:
        scan = obj.scans.first()
        return scan.verdict if scan else "pending"

    def get_extraction(self, obj) -> dict | None:
        extraction = getattr(obj, "extraction", None)
        if extraction is None:
            return None
        return {
            "handler": extraction.handler,
            "charCount": extraction.char_count,
            "pageCount": extraction.page_count,
            "truncated": extraction.truncated,
            "metadataOnly": extraction.metadata_only,
            "error": extraction.error,
        }


class AttachmentUploadSerializer(serializers.Serializer):
    """
    Upload body. NO type restriction and NO count restriction (R25).

    ``file`` is a single upload; the client posts once per file so per-file failure is
    per-file rather than losing the whole batch.
    """

    file = serializers.FileField()
    thread_id = serializers.CharField()
