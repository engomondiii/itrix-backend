"""Admin for AI Engine generation logs (read-only telemetry)."""

from __future__ import annotations

from django.contrib import admin

from apps.ai_engine.models import GenerationLog
from apps.core.admin import ReadOnlyAdmin, bool_badge, pretty_json, truncate


@admin.register(GenerationLog)
class GenerationLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "lead", "review_session", "product_route", "ai_col", "chunk_count", "ok_col", "error_col")
    list_filter = ("used_ai", "ok", "product_route")
    search_fields = ("lead__company", "lead__email", "review_session__id", "error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead", "review_session")
    readonly_fields = ("prohibited_removed_pretty", "quant_hedged_pretty")
    fieldsets = (
        ("Generation", {"fields": (("lead", "review_session"), ("product_route", "used_ai", "chunk_count"), ("ok",), "id")}),
        ("Claims discipline", {"fields": ("prohibited_removed_pretty", "quant_hedged_pretty")}),
        ("Error", {"fields": ("error",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="AI", ordering="used_ai")
    def ai_col(self, obj):
        return bool_badge(obj.used_ai, "AI", "template")

    @admin.display(description="OK", ordering="ok", boolean=True)
    def ok_col(self, obj):
        return obj.ok

    @admin.display(description="Error")
    def error_col(self, obj):
        return truncate(obj.error, 60)

    @admin.display(description="Prohibited claims removed")
    def prohibited_removed_pretty(self, obj):
        return pretty_json(obj.prohibited_removed)

    @admin.display(description="Quantitative claims hedged")
    def quant_hedged_pretty(self, obj):
        return pretty_json(obj.quant_hedged)
