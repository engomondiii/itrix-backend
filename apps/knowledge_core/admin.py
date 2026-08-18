"""
Admin for the Knowledge Core — register documents here, run ingestion, and
inspect the chunks and claim records that came out of it.

This is the one admin that carries a real *action* (ingest), because the
knowledge team works from here rather than from the cockpit.
"""

from __future__ import annotations

from django.contrib import admin, messages

from apps.core.admin import (
    ItrixModelAdmin,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    count_link,
    truncate,
)
from apps.knowledge_core.models import ClaimRecord, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.services.ingestion_pipeline import ingest_document


class KnowledgeChunkInline(ReadOnlyTabularInline):
    model = KnowledgeChunk
    fields = ("chunk_index", "heading", "token_estimate", "disclosure_level", "embedded", "vector_id")
    ordering = ("chunk_index",)
    verbose_name_plural = "Chunks"


class ClaimRecordInline(ReadOnlyTabularInline):
    model = ClaimRecord
    fields = ("created_at", "disclosure_level", "is_prohibited", "public_reference", "text_col")
    readonly_fields = ("text_col",)
    verbose_name_plural = "Claim records"

    @admin.display(description="Claim")
    def text_col(self, obj):
        return truncate(obj.text, 140)


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(ItrixModelAdmin):
    list_display = ("title", "namespace", "disclosure_col", "ingestion_col", "chunks_col", "last_ingested_at", "updated_at")
    list_filter = ("namespace", "disclosure_level", "ingestion_status")
    search_fields = ("title", "file_path", "namespace", "content_hash")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("id", "ingestion_status", "ingestion_error", "chunk_count", "content_hash", "last_ingested_at", "created_at", "updated_at")
    fieldsets = (
        ("Document", {"fields": ("title", ("namespace", "disclosure_level"), "uploaded_file", "file_path")}),
        ("Ingestion", {"fields": (("ingestion_status", "chunk_count", "last_ingested_at"), "ingestion_error", "content_hash")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )
    inlines = [KnowledgeChunkInline, ClaimRecordInline]
    actions = ["run_ingestion", "run_ingestion_dry"]

    @admin.display(description="Disclosure", ordering="disclosure_level")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_level)

    @admin.display(description="Ingestion", ordering="ingestion_status")
    def ingestion_col(self, obj):
        return badge(obj.ingestion_status)

    @admin.display(description="Chunks", ordering="chunk_count")
    def chunks_col(self, obj):
        return count_link(KnowledgeChunk, obj.chunk_count, document__id__exact=obj.pk)

    @admin.action(description="Run ingestion for selected documents")
    def run_ingestion(self, request, queryset):
        ok, failed = 0, []
        for doc in queryset:
            result = ingest_document(doc)
            if result.ok:
                ok += 1
            else:
                failed.append(f"{doc.title}: {result.error or 'failed'}")
        level = messages.SUCCESS if not failed else messages.WARNING
        text = f"Ingestion complete: {ok}/{queryset.count()} succeeded."
        if failed:
            text += " Failed — " + "; ".join(failed[:5]) + (" …" if len(failed) > 5 else "")
        self.message_user(request, text, level)

    @admin.action(description="Dry-run ingestion (no writes) for selected documents")
    def run_ingestion_dry(self, request, queryset):
        ok = 0
        for doc in queryset:
            if ingest_document(doc, dry_run=True).ok:
                ok += 1
        self.message_user(request, f"Dry run: {ok}/{queryset.count()} would ingest cleanly.", messages.INFO)


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(ItrixModelAdmin):
    list_display = ("document", "chunk_index", "heading_col", "namespace", "disclosure_col", "token_estimate", "embedded_col")
    list_filter = ("namespace", "disclosure_level", "embedded")
    search_fields = ("heading", "text", "vector_id", "document__title")
    raw_id_fields = ("document",)
    ordering = ("document", "chunk_index")
    list_select_related = ("document",)
    readonly_fields = ("id", "document", "chunk_index", "vector_id", "embedded", "token_estimate", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": (("document", "chunk_index"), ("namespace", "disclosure_level"), "heading")}),
        ("Text", {"fields": ("text",)}),
        ("Vector", {"fields": (("vector_id", "embedded", "token_estimate"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Heading", ordering="heading")
    def heading_col(self, obj):
        return truncate(obj.heading, 60)

    @admin.display(description="Disclosure", ordering="disclosure_level")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_level)

    @admin.display(description="Embedded", ordering="embedded")
    def embedded_col(self, obj):
        return bool_badge(obj.embedded, "embedded", "pending")


@admin.register(ClaimRecord)
class ClaimRecordAdmin(ItrixModelAdmin):
    list_display = ("text_col", "disclosure_col", "prohibited_col", "public_reference", "document", "created_at")
    list_display_links = ("text_col",)
    list_filter = ("disclosure_level", "is_prohibited", ("document", admin.EmptyFieldListFilter))
    search_fields = ("text", "public_reference", "document__title")
    raw_id_fields = ("document",)
    ordering = ("-created_at",)
    list_select_related = ("document",)
    fields = ("document", "text", ("disclosure_level", "is_prohibited"), "public_reference", ("created_at", "updated_at"), "id")

    @admin.display(description="Claim", ordering="text")
    def text_col(self, obj):
        return truncate(obj.text, 100)

    @admin.display(description="Disclosure", ordering="disclosure_level")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_level)

    @admin.display(description="Prohibited", ordering="is_prohibited")
    def prohibited_col(self, obj):
        return badge("prohibited", "danger") if obj.is_prohibited else badge("allowed", "success")
