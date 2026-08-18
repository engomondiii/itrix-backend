"""Admin for generated result pages (read-only — they are generated, not authored)."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, bool_badge, pretty_json, tier_badge, truncate
from apps.result_page.models import ResultPage


@admin.register(ResultPage)
class ResultPageAdmin(ReadOnlyAdmin):
    list_display = ("generated_at", "lead", "tier_col", "product_route", "license_pathway", "ai_col", "next_step_col")
    list_filter = ("tier", "product_route", "license_pathway", "used_ai")
    search_fields = ("lead__company", "lead__email", "problem_mirror", "alpha_fit_summary")
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    list_select_related = ("lead",)
    readonly_fields = ("score_breakdown_pretty", "primary_technologies_pretty", "diagnosis_pretty", "kpi_preview_pretty", "proof_preview_pretty")
    fieldsets = (
        ("Page", {"fields": (("lead", "generated_at"), ("tier", "product_route", "license_pathway"), "used_ai", "id")}),
        ("Narrative", {"fields": ("problem_mirror", "alpha_fit_summary", "recommended_next_step")}),
        ("Structured", {"fields": ("diagnosis_pretty", "primary_technologies_pretty", "kpi_preview_pretty", "proof_preview_pretty", "score_breakdown_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Tier", ordering="tier")
    def tier_col(self, obj):
        return tier_badge(obj.tier)

    @admin.display(description="AI", ordering="used_ai")
    def ai_col(self, obj):
        return bool_badge(obj.used_ai, "AI", "template")

    @admin.display(description="Next step")
    def next_step_col(self, obj):
        return truncate(obj.recommended_next_step, 70)

    @admin.display(description="Score breakdown")
    def score_breakdown_pretty(self, obj):
        return pretty_json(obj.score_breakdown)

    @admin.display(description="Primary technologies")
    def primary_technologies_pretty(self, obj):
        return pretty_json(obj.primary_technologies)

    @admin.display(description="Diagnosis")
    def diagnosis_pretty(self, obj):
        return pretty_json(obj.diagnosis)

    @admin.display(description="KPI preview")
    def kpi_preview_pretty(self, obj):
        return pretty_json(obj.kpi_preview)

    @admin.display(description="Proof preview")
    def proof_preview_pretty(self, obj):
        return pretty_json(obj.proof_preview)
