"""
Admin for the Knowledge Core — register documents here, run ingestion, and
inspect the chunks and claim records that came out of it.

This is the one admin that carries a real *action* (ingest), because the
knowledge team works from here rather than from the cockpit.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from apps.core.admin import (
    ItrixModelAdmin,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    count_link,
    truncate,
)
from apps.knowledge_core.models import (
    ClaimRecord,
    ContentAuthorization,
    HardFact,
    KnowledgeChunk,
    KnowledgeConflict,
    KnowledgeDocument,
)
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


# ── Governance registries ────────────────────────────────────────────────────
# Retrieval is not authorization. An NDA is only a prerequisite; restricted
# content stays invisible until a ContentAuthorization row names the subject.
# These three tables are where that call is actually made, so unlike the rest of
# the pipeline they are edited here rather than merely inspected.

AUTHORITY_TONES = {
    "authoritative": "success",
    "governing": "info",
    "working": "warning",
    "legacy": "muted",
}


@admin.register(HardFact)
class HardFactAdmin(ItrixModelAdmin):
    """The structured answer to "is it a filing or a grant?".

    Prose similarity must never promote an application into a granted patent, so
    for these claims the registry — not the retrieved chunk — is the source.
    """

    list_display = (
        "key", "category_col", "jurisdiction", "status_col", "authority_col",
        "current_col", "disclosure_col", "last_verified_at",
    )
    list_filter = ("category", "source_authority", "is_current", "disclosure_level")
    search_fields = (
        "key", "public_statement", "internal_reference",
        "official_application_number", "verified_grant_number",
    )
    raw_id_fields = ("source_document",)
    ordering = ("category", "key")
    date_hierarchy = "created_at"
    fieldsets = (
        ("Fact", {"fields": ("key", ("category", "jurisdiction"), "public_statement")}),
        ("Register", {
            "fields": (
                ("official_application_number", "filing_date"),
                ("publication_status", "prosecution_status"),
                "verified_grant_number", "ownership_assignment", "internal_reference",
            ),
            "description": "Leave the grant number empty unless a grant has actually "
                           "issued — it is what stops a filing being described as granted.",
        }),
        ("Provenance", {"fields": ("source_document", "source_reference",
                                   ("source_authority", "is_current"), "last_verified_at")}),
        ("Disclosure", {"fields": (("disclosure_level", "claim_ceiling"), "approved_audience")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Category", ordering="category")
    def category_col(self, obj):
        return badge(obj.get_category_display(), "info")

    @admin.display(description="Status")
    def status_col(self, obj):
        if obj.verified_grant_number:
            return badge("granted", "success")
        return badge(obj.prosecution_status or obj.publication_status or "filed", "warning")

    @admin.display(description="Authority", ordering="source_authority")
    def authority_col(self, obj):
        return badge(obj.source_authority, AUTHORITY_TONES.get(obj.source_authority))

    @admin.display(description="Current", ordering="is_current")
    def current_col(self, obj):
        return bool_badge(obj.is_current, "current", "superseded")

    @admin.display(description="Disclosure", ordering="disclosure_level")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_level)


@admin.register(ContentAuthorization)
class ContentAuthorizationAdmin(ItrixModelAdmin):
    """The second, mandatory gate in front of restricted content.

    Granting one of these is a disclosure decision, not an account setting: it
    names a single document and a single subject. Revoke rather than delete, so
    a grant that was once live stays on the record.
    """

    list_display = ("document", "subject_col", "scope", "active_col", "expires_at",
                    "authorized_by", "created_at")
    list_filter = ("subject_kind", "active", "document__disclosure_level")
    search_fields = ("subject_id", "document__title", "reason", "scope")
    raw_id_fields = ("document", "authorized_by")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("document", "authorized_by")
    fieldsets = (
        ("Grant", {"fields": ("document", ("subject_kind", "subject_id"), "scope")}),
        ("Justification", {"fields": ("reason", "authorized_by")}),
        ("Validity", {"fields": (("active", "expires_at"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )
    actions = ["revoke_authorizations"]

    @admin.display(description="Subject", ordering="subject_kind")
    def subject_col(self, obj):
        return format_html(
            "{} {}", badge(obj.get_subject_kind_display(), "info"), truncate(obj.subject_id, 40)
        )

    @admin.display(description="Active", ordering="active")
    def active_col(self, obj):
        if not obj.active:
            return badge("revoked", "danger")
        if obj.expires_at and obj.expires_at <= timezone.now():
            return badge("expired", "danger")
        return badge("active", "success")

    @admin.action(description="Revoke selected authorizations")
    def revoke_authorizations(self, request, queryset):
        revoked = queryset.filter(active=True).update(active=False)
        self.message_user(request, f"Revoked {revoked} authorization(s).", messages.WARNING)


@admin.register(KnowledgeConflict)
class KnowledgeConflictAdmin(ItrixModelAdmin):
    """Two equally authoritative sources disagreed and retrieval could not choose.

    The rows are written by the retriever, so everything except ``resolved`` is
    read-only here — the decision this admin records is "a human has dealt with
    it", not a rewrite of what was observed.
    """

    list_display = ("topic_col", "authority_col", "sources_col", "resolved_col", "created_at")
    list_display_links = ("topic_col",)
    list_filter = ("authority", "resolved")
    search_fields = ("topic", "query_fingerprint", "detail")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("query_fingerprint", "topic", "authority", "document_ids", "detail")
    fields = ("topic", ("authority", "resolved"), "query_fingerprint", "document_ids", "detail",
              ("created_at", "updated_at"), "id")
    actions = ["mark_resolved"]

    @admin.display(description="Topic", ordering="topic")
    def topic_col(self, obj):
        return truncate(obj.topic or obj.detail, 80)

    @admin.display(description="Authority", ordering="authority")
    def authority_col(self, obj):
        return badge(obj.authority, AUTHORITY_TONES.get(obj.authority))

    @admin.display(description="Sources")
    def sources_col(self, obj):
        return badge(f"{len(obj.document_ids or [])} docs", "muted")

    @admin.display(description="Resolved", ordering="resolved")
    def resolved_col(self, obj):
        return bool_badge(obj.resolved, "resolved", "open")

    @admin.action(description="Mark selected conflicts resolved")
    def mark_resolved(self, request, queryset):
        updated = queryset.filter(resolved=False).update(resolved=True)
        self.message_user(request, f"Marked {updated} conflict(s) resolved.", messages.SUCCESS)
