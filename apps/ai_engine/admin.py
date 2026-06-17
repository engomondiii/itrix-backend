"""Admin for AI Engine generation logs (read-only telemetry)."""

from __future__ import annotations

from django.contrib import admin

from apps.ai_engine.models import GenerationLog


@admin.register(GenerationLog)
class GenerationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "product_route", "used_ai", "chunk_count", "ok", "created_at")
    list_filter = ("used_ai", "ok", "product_route")
    readonly_fields = (
        "lead",
        "review_session",
        "product_route",
        "used_ai",
        "chunk_count",
        "prohibited_removed",
        "quant_hedged",
        "ok",
        "error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False
