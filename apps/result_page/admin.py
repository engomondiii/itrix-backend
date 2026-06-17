"""Admin for generated result pages (read-mostly)."""

from __future__ import annotations

from django.contrib import admin

from apps.result_page.models import ResultPage


@admin.register(ResultPage)
class ResultPageAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "tier", "product_route", "used_ai", "generated_at")
    list_filter = ("tier", "product_route", "used_ai")
    readonly_fields = (
        "lead",
        "tier",
        "score_breakdown",
        "product_route",
        "license_pathway",
        "primary_technologies",
        "problem_mirror",
        "diagnosis",
        "alpha_fit_summary",
        "kpi_preview",
        "proof_preview",
        "recommended_next_step",
        "used_ai",
        "generated_at",
        "created_at",
        "updated_at",
    )
