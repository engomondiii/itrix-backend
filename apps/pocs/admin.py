"""Admin for proofs of concept."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, badge, pretty_json
from apps.pocs.models import PoC


@admin.register(PoC)
class PoCAdmin(ItrixModelAdmin):
    list_display = ("lead_name", "company", "status_col", "start_date", "duration_weeks", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("lead_name", "company", "scope", "success_metrics", "lead__email")
    raw_id_fields = ("lead",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "milestones_pretty", "kpis_pretty", "risks_pretty")
    fieldsets = (
        (None, {"fields": (("lead", "lead_name", "company"), ("status", "start_date", "duration_weeks"))}),
        ("Scope", {"fields": ("scope", "success_metrics")}),
        ("Plan", {"fields": ("milestones", "milestones_pretty", "kpis", "kpis_pretty", "risks", "risks_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Milestones (rendered)")
    def milestones_pretty(self, obj):
        return pretty_json(obj.milestones)

    @admin.display(description="KPIs (rendered)")
    def kpis_pretty(self, obj):
        return pretty_json(obj.kpis)

    @admin.display(description="Risks (rendered)")
    def risks_pretty(self, obj):
        return pretty_json(obj.risks)
