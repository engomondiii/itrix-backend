"""Admin for agent runs (read-only audit of every agent invocation)."""

from __future__ import annotations

from django.contrib import admin

from apps.agents.models import AgentRun
from apps.core.admin import ReadOnlyAdmin, badge, bool_badge, claim_level_badge, pretty_json, truncate


@admin.register(AgentRun)
class AgentRunAdmin(ReadOnlyAdmin):
    list_display = (
        "created_at",
        "agent_key",
        "status_col",
        "governance_col",
        "claim_col",
        "ai_col",
        "duration_col",
        "lead",
        "client_id",
        "error_col",
    )
    list_filter = ("agent_key", "status", "governance_status", "used_ai", "claim_level")
    search_fields = ("agent_key", "client_id", "lead__id", "lead__company", "lead__email", "error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead",)
    readonly_fields = ("input_summary_pretty", "output_pretty", "chunk_ids_pretty")
    fieldsets = (
        ("Run", {"fields": (("agent_key", "status", "used_ai"), ("governance_status", "claim_level"), ("lead", "client_id"), ("duration_ms",), "id")}),
        ("Input", {"fields": ("input_summary_pretty",)}),
        ("Output", {"fields": ("output_pretty", "chunk_ids_pretty")}),
        ("Error", {"fields": ("error",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Governance", ordering="governance_status")
    def governance_col(self, obj):
        return badge(obj.governance_status)

    @admin.display(description="Claim", ordering="claim_level")
    def claim_col(self, obj):
        return claim_level_badge(obj.claim_level)

    @admin.display(description="AI", ordering="used_ai")
    def ai_col(self, obj):
        return bool_badge(obj.used_ai, "AI", "rules")

    @admin.display(description="Duration", ordering="duration_ms")
    def duration_col(self, obj):
        ms = obj.duration_ms or 0
        return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"

    @admin.display(description="Error")
    def error_col(self, obj):
        return truncate(obj.error, 60)

    @admin.display(description="Input summary")
    def input_summary_pretty(self, obj):
        return pretty_json(obj.input_summary)

    @admin.display(description="Output")
    def output_pretty(self, obj):
        return pretty_json(obj.output)

    @admin.display(description="Chunk ids")
    def chunk_ids_pretty(self, obj):
        return pretty_json(obj.chunk_ids)
