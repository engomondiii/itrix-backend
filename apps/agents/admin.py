"""Admin for agent runs (read-only audit)."""

from __future__ import annotations

from django.contrib import admin

from apps.agents.models import AgentRun


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_key", "lead", "status", "used_ai", "governance_status", "claim_level", "duration_ms", "created_at")
    list_filter = ("agent_key", "status", "used_ai", "governance_status")
    search_fields = ("agent_key", "lead__id", "client_id")
    readonly_fields = tuple(f.name for f in AgentRun._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
