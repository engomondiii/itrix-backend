"""Attachment admin — read-mostly, with the risk flags visible to staff."""

from __future__ import annotations

from django.contrib import admin

from apps.attachments.models import (
    Attachment,
    AttachmentAuditEntry,
    AttachmentExcerpt,
    AttachmentExtraction,
    AttachmentScan,
)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("filename", "status", "detected_mime", "bytes", "pre_nda",
                    "retention_expires_at", "created_at")
    list_filter = ("status", "pre_nda", "uploaded_by_kind")
    search_fields = ("filename", "sha256")
    readonly_fields = ("sha256", "blob_key", "risk_flags")


@admin.register(AttachmentScan)
class AttachmentScanAdmin(admin.ModelAdmin):
    list_display = ("attachment", "engine", "verdict", "scanned_at")
    list_filter = ("verdict", "engine")


@admin.register(AttachmentExtraction)
class AttachmentExtractionAdmin(admin.ModelAdmin):
    list_display = ("attachment", "handler", "char_count", "metadata_only", "duration_ms")
    list_filter = ("handler", "metadata_only")


@admin.register(AttachmentAuditEntry)
class AttachmentAuditEntryAdmin(admin.ModelAdmin):
    list_display = ("attachment", "action", "plane", "subject", "created_at")
    list_filter = ("action", "plane")


admin.site.register(AttachmentExcerpt)
