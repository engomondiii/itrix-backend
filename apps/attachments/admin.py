"""
Attachment admin — read-mostly, with the risk flags visible to staff.

An Attachment's change page is the whole story of one upload: scan verdicts,
the sandbox extraction, the excerpts that were selected for context, and the
audit trail of every access. Bytes are never served from here (blob keys are
displayed but not linked) — the download endpoint enforces the plane rules.
"""

from __future__ import annotations

from django.contrib import admin
from django.template.defaultfilters import filesizeformat

from apps.attachments.models import (
    Attachment,
    AttachmentAuditEntry,
    AttachmentExcerpt,
    AttachmentExtraction,
    AttachmentScan,
)
from apps.core.admin import (
    AppendOnlyAdmin,
    ItrixModelAdmin,
    ReadOnlyAdmin,
    ReadOnlyStackedInline,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    pretty_json,
    truncate,
)


class AttachmentScanInline(ReadOnlyTabularInline):
    model = AttachmentScan
    fields = ("scanned_at", "engine", "verdict", "detail")
    ordering = ("-scanned_at",)
    verbose_name_plural = "Scans"


class AttachmentExtractionInline(ReadOnlyStackedInline):
    model = AttachmentExtraction
    fields = (("handler", "metadata_only", "truncated"), ("page_count", "char_count", "duration_ms"), "error", "text_preview")
    readonly_fields = ("text_preview",)
    verbose_name_plural = "Extraction"

    @admin.display(description="Text (first 2,000 chars)")
    def text_preview(self, obj):
        return (obj.text or "")[:2000] or "—"


class AttachmentExcerptInline(ReadOnlyTabularInline):
    model = AttachmentExcerpt
    fields = ("ordinal", "char_count", "text_col")
    readonly_fields = ("text_col",)
    ordering = ("ordinal",)
    verbose_name_plural = "Excerpts"

    @admin.display(description="Text")
    def text_col(self, obj):
        return truncate(obj.text, 200)


class AttachmentAuditEntryInline(ReadOnlyTabularInline):
    model = AttachmentAuditEntry
    fields = ("created_at", "action", "plane", "subject", "purpose", "detail")
    ordering = ("-created_at",)
    verbose_name_plural = "Audit trail"


@admin.register(Attachment)
class AttachmentAdmin(ItrixModelAdmin):
    list_display = ("filename_col", "status_col", "detected_mime", "size_col", "uploaded_by_kind", "pre_nda_col", "thread", "retention_expires_at", "created_at")
    list_display_links = ("filename_col",)
    list_filter = ("status", "pre_nda", "uploaded_by_kind", "detected_mime", ("deleted_at", admin.EmptyFieldListFilter))
    search_fields = ("filename", "sha256", "uploaded_by_id", "thread__id", "thread__title", "visitor_note")
    raw_id_fields = ("thread",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("thread",)
    readonly_fields = (
        "id",
        "thread",
        "uploaded_by_kind",
        "uploaded_by_id",
        "filename",
        "declared_mime",
        "detected_mime",
        "bytes",
        "sha256",
        "blob_key",
        "status",
        "pre_nda",
        "purged_at",
        "risk_flags_pretty",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "File",
            {
                "fields": (
                    ("filename", "status"),
                    ("declared_mime", "detected_mime", "bytes"),
                    ("sha256",),
                    ("blob_key",),
                    "visitor_note",
                    "id",
                )
            },
        ),
        ("Provenance", {"fields": (("thread",), ("uploaded_by_kind", "uploaded_by_id"), "pre_nda")}),
        ("Risk", {"fields": ("risk_flags_pretty",)}),
        ("Lifecycle", {"fields": (("retention_expires_at", "deleted_at", "purged_at"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [AttachmentScanInline, AttachmentExtractionInline, AttachmentExcerptInline, AttachmentAuditEntryInline]

    def has_add_permission(self, request):
        return False

    @admin.display(description="File", ordering="filename")
    def filename_col(self, obj):
        return truncate(obj.filename, 50)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Size", ordering="bytes")
    def size_col(self, obj):
        return filesizeformat(obj.bytes)

    @admin.display(description="Pre-NDA", ordering="pre_nda")
    def pre_nda_col(self, obj):
        return bool_badge(obj.pre_nda, "pre-NDA", "post-NDA")

    @admin.display(description="Risk flags")
    def risk_flags_pretty(self, obj):
        return pretty_json(obj.risk_flags)


@admin.register(AttachmentScan)
class AttachmentScanAdmin(ReadOnlyAdmin):
    list_display = ("scanned_at", "attachment", "engine", "verdict_col", "detail_col")
    list_filter = ("verdict", "engine")
    search_fields = ("attachment__filename", "attachment__sha256", "detail")
    date_hierarchy = "scanned_at"
    ordering = ("-scanned_at",)
    list_select_related = ("attachment",)

    @admin.display(description="Verdict", ordering="verdict")
    def verdict_col(self, obj):
        return badge(obj.verdict)

    @admin.display(description="Detail")
    def detail_col(self, obj):
        return truncate(obj.detail, 90)


@admin.register(AttachmentExtraction)
class AttachmentExtractionAdmin(ReadOnlyAdmin):
    list_display = ("attachment", "handler", "page_count", "char_count", "truncated", "metadata_only", "duration_ms", "created_at")
    list_filter = ("handler", "metadata_only", "truncated")
    search_fields = ("attachment__filename", "handler", "error")
    ordering = ("-created_at",)
    list_select_related = ("attachment",)


@admin.register(AttachmentExcerpt)
class AttachmentExcerptAdmin(ReadOnlyAdmin):
    list_display = ("attachment", "ordinal", "char_count", "text_col")
    search_fields = ("attachment__filename", "text")
    ordering = ("attachment", "ordinal")
    list_select_related = ("attachment",)

    @admin.display(description="Text")
    def text_col(self, obj):
        return truncate(obj.text, 140)


@admin.register(AttachmentAuditEntry)
class AttachmentAuditEntryAdmin(AppendOnlyAdmin):
    list_display = ("created_at", "attachment", "action", "plane", "subject", "purpose", "detail_col")
    list_filter = ("action", "plane", "purpose")
    search_fields = ("attachment__filename", "subject", "detail", "action")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("attachment",)

    @admin.display(description="Detail")
    def detail_col(self, obj):
        return truncate(obj.detail, 90)
