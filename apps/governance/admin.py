"""
Admin for the governance fabric: claim cards, approval requests, stream-guard hits.

Claim cards are the one hand-maintained registry here. Approval requests are
worked in the cockpit (they carry the two-approver protocol), so this admin
shows them read-only. Stream-guard hits are telemetry.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import (
    AppendOnlyAdmin,
    ItrixModelAdmin,
    ReadOnlyAdmin,
    badge,
    claim_level_badge,
    pretty_json,
    truncate,
)
from apps.governance.models import ApprovalRequest, ClaimCard, StreamGuardHit


@admin.register(ClaimCard)
class ClaimCardAdmin(ItrixModelAdmin):
    list_display = ("key", "title", "level_col", "disclosure_col", "owner", "is_active", "updated_at")
    list_filter = ("claim_level", "disclosure_ceiling", "is_active", ("owner", admin.RelatedOnlyFieldListFilter))
    search_fields = ("key", "title", "approved_wording", "claim_record_id")
    autocomplete_fields = ("owner",)
    ordering = ("claim_level", "key")
    prepopulated_fields = {"key": ("title",)}
    fieldsets = (
        (None, {"fields": (("key", "title"), ("claim_level", "disclosure_ceiling"), ("owner", "is_active"))}),
        ("Wording", {"fields": ("approved_wording", "notes")}),
        ("Links", {"fields": ("claim_record_id", "id")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Level", ordering="claim_level")
    def level_col(self, obj):
        return claim_level_badge(obj.claim_level)

    @admin.display(description="Ceiling", ordering="disclosure_ceiling")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_ceiling)


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(AppendOnlyAdmin):
    list_display = ("created_at", "status_col", "level_col", "agent_key", "lead", "draft_col", "first_approver", "second_approver", "resolved_at")
    list_filter = ("status", "claim_level", "agent_key", ("first_approver", admin.RelatedOnlyFieldListFilter))
    search_fields = ("message_id", "conversation_id", "client_id", "draft_body", "final_body", "lead__company", "lead__email")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead", "first_approver", "second_approver")
    readonly_fields = ("cited_pretty", "requires_second_col")
    fieldsets = (
        (
            "Request",
            {
                "fields": (
                    ("status", "claim_level", "requires_second_col"),
                    ("agent_key", "lead", "client_id"),
                    ("message_id", "conversation_id"),
                    "id",
                )
            },
        ),
        ("Bodies", {"fields": ("draft_body", "final_body", "reason")}),
        ("Approvers", {"fields": (("first_approver", "second_approver"), "resolved_at")}),
        ("Citations", {"fields": ("cited_pretty",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Level", ordering="claim_level")
    def level_col(self, obj):
        return claim_level_badge(obj.claim_level)

    @admin.display(description="Draft")
    def draft_col(self, obj):
        return truncate(obj.draft_body, 90)

    @admin.display(description="Needs 2nd approver", boolean=True)
    def requires_second_col(self, obj):
        return obj.requires_second_approver

    @admin.display(description="Cited chunk ids")
    def cited_pretty(self, obj):
        return pretty_json(obj.cited_chunk_ids)


@admin.register(StreamGuardHit)
class StreamGuardHitAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "kind_col", "category", "pattern", "matched_col", "agent_key", "plane", "journey_state", "matcher_pass", "thread_id")
    list_filter = ("kind", "category", "matcher_pass", "agent_key", "plane", "journey_state")
    search_fields = ("thread_id", "message_id", "pattern", "matched_text", "category")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("meta_pretty",)
    fieldsets = (
        ("Hit", {"fields": (("kind", "category", "matcher_pass"), ("pattern", "matched_text"), ("position", "discarded_chars"))}),
        ("Where", {"fields": (("thread_id", "message_id"), ("agent_key", "plane", "journey_state"))}),
        ("Meta", {"fields": ("meta_pretty", "id"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        return badge(obj.kind)

    @admin.display(description="Matched")
    def matched_col(self, obj):
        return truncate(obj.matched_text, 60)

    @admin.display(description="Meta")
    def meta_pretty(self, obj):
        return pretty_json(obj.meta)
