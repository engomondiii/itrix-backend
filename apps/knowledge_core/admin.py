"""Admin for Knowledge Core — register documents from here and run ingestion."""

from __future__ import annotations

from django.contrib import admin, messages

from apps.knowledge_core.models import ClaimRecord, KnowledgeChunk, KnowledgeDocument
from apps.knowledge_core.services.ingestion_pipeline import ingest_document


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    readonly_fields = ("chunk_index", "heading", "token_estimate", "vector_id", "embedded")
    fields = ("chunk_index", "heading", "token_estimate", "vector_id", "embedded")
    can_delete = False
    show_change_link = False


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "namespace", "disclosure_level", "ingestion_status", "chunk_count", "last_ingested_at")
    list_filter = ("namespace", "disclosure_level", "ingestion_status")
    search_fields = ("title", "file_path", "namespace")
    readonly_fields = ("id", "ingestion_status", "ingestion_error", "chunk_count", "content_hash", "last_ingested_at", "created_at", "updated_at")
    inlines = [KnowledgeChunkInline]
    actions = ["run_ingestion"]

    @admin.action(description="Run ingestion for selected documents")
    def run_ingestion(self, request, queryset):
        ok = 0
        for doc in queryset:
            result = ingest_document(doc)
            ok += 1 if result.ok else 0
        self.message_user(request, f"Ingestion complete: {ok}/{queryset.count()} succeeded.", messages.INFO)


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "chunk_index", "namespace", "disclosure_level", "embedded")
    list_filter = ("namespace", "disclosure_level", "embedded")
    search_fields = ("heading", "text", "vector_id")


@admin.register(ClaimRecord)
class ClaimRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "disclosure_level", "is_prohibited", "public_reference", "created_at")
    list_filter = ("disclosure_level", "is_prohibited")
    search_fields = ("text", "public_reference")
