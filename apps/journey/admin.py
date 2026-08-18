"""
Admin for the journey: the transition audit trail, and the per-thread
artifacts / question suggestions / coverage snapshots.

Transitions are append-only evidence of state changes. Artifacts are governed
payloads: staff may pin/unpin one, everything else about it is system-owned.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import (
    AppendOnlyAdmin,
    ItrixModelAdmin,
    ReadOnlyAdmin,
    badge,
    bool_badge,
    link_to,
    pretty_json,
    short_id,
    truncate,
)
from apps.journey.models import Artifact, CoverageSnapshot, JourneyTransition, QuestionSuggestion


@admin.register(JourneyTransition)
class JourneyTransitionAdmin(AppendOnlyAdmin):
    list_display = ("created_at", "lead", "from_col", "arrow", "to_col", "event_col", "reveal", "actor")
    list_filter = ("to_state", "from_state", "event", "reveal", ("actor", admin.RelatedOnlyFieldListFilter))
    search_fields = ("lead__id", "lead__company", "lead__email", "event")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead", "actor")
    readonly_fields = ("meta_pretty",)
    fields = ("lead", ("from_state", "to_state"), ("event", "reveal"), "actor", "meta_pretty", ("created_at", "updated_at"))

    @admin.display(description="From", ordering="from_state")
    def from_col(self, obj):
        return badge(obj.from_state, "muted")

    @admin.display(description="")
    def arrow(self, obj):
        return "→"

    @admin.display(description="To", ordering="to_state")
    def to_col(self, obj):
        return badge(obj.to_state, "primary")

    @admin.display(description="Event", ordering="event")
    def event_col(self, obj):
        return badge(obj.event, "info")

    @admin.display(description="Meta")
    def meta_pretty(self, obj):
        return pretty_json(obj.meta)


@admin.register(Artifact)
class ArtifactAdmin(ItrixModelAdmin):
    """System-generated. Staff may pin an artifact; nothing else is editable."""

    list_display = ("created_at", "type", "version", "thread", "disclosure_col", "governance_col", "current_col", "pinned")
    list_filter = ("type", "disclosure_level", "governance_status", "pinned", ("superseded_by", admin.EmptyFieldListFilter))
    search_fields = ("id", "type", "thread__id", "thread__title", "generated_by_run")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_editable = ("pinned",)
    list_select_related = ("thread", "superseded_by")
    readonly_fields = (
        "id",
        "thread",
        "type",
        "version",
        "disclosure_level",
        "governance_status",
        "generated_by_run",
        "capability_token",
        "superseded_by_link",
        "payload_pretty",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Artifact",
            {
                "fields": (
                    ("type", "version", "pinned"),
                    ("thread", "superseded_by_link"),
                    ("disclosure_level", "governance_status"),
                    ("generated_by_run", "id"),
                )
            },
        ),
        ("Payload", {"fields": ("payload_pretty",)}),
        ("Capability token", {"fields": ("capability_token",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Disclosure", ordering="disclosure_level")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_level)

    @admin.display(description="Governance", ordering="governance_status")
    def governance_col(self, obj):
        return badge(obj.governance_status)

    @admin.display(description="Current", boolean=True)
    def current_col(self, obj):
        return obj.is_current

    @admin.display(description="Superseded by")
    def superseded_by_link(self, obj):
        return link_to(obj.superseded_by, f"v{obj.superseded_by.version} · {short_id(obj.superseded_by.id)}") if obj.superseded_by else bool_badge(True, "current", "")

    @admin.display(description="Payload")
    def payload_pretty(self, obj):
        return pretty_json(obj.payload)


@admin.register(QuestionSuggestion)
class QuestionSuggestionAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "thread", "target_dimension", "primary_col", "message")
    list_filter = ("target_dimension",)
    search_fields = ("primary_text", "thread__id", "thread__title", "agent_run_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("thread", "message")
    readonly_fields = ("chips_pretty",)
    fields = ("thread", "message", "target_dimension", "primary_text", "chips_pretty", "agent_run_id", ("created_at", "updated_at"))

    @admin.display(description="Question", ordering="primary_text")
    def primary_col(self, obj):
        return truncate(obj.primary_text, 100)

    @admin.display(description="Chips")
    def chips_pretty(self, obj):
        return pretty_json(obj.chips)


@admin.register(CoverageSnapshot)
class CoverageSnapshotAdmin(ReadOnlyAdmin):
    list_display = ("thread", "dimension", "status_col", "evidence_message_id", "updated_at")
    list_filter = ("status", "dimension")
    search_fields = ("thread__id", "thread__title", "dimension", "evidence_message_id")
    ordering = ("thread", "dimension")
    list_select_related = ("thread",)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)
