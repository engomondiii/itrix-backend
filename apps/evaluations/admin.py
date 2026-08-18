"""Admin for paid evaluations."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, badge, pretty_json
from apps.evaluations.models import Evaluation


@admin.register(Evaluation)
class EvaluationAdmin(ItrixModelAdmin):
    list_display = ("lead_name", "company", "pkg", "status_col", "fee", "timeline", "created_at", "updated_at")
    list_filter = ("status", "pkg")
    search_fields = ("lead_name", "company", "scope", "lead__email")
    raw_id_fields = ("lead",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "kpis_pretty")
    fieldsets = (
        (None, {"fields": (("lead", "lead_name", "company"), ("pkg", "status"))}),
        ("Commercials", {"fields": (("fee", "timeline"), "scope")}),
        ("KPIs", {"fields": ("kpis", "kpis_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="KPIs (rendered)")
    def kpis_pretty(self, obj):
        return pretty_json(obj.kpis)
