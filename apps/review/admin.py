"""Admin for review sessions (operational visibility for the team)."""

from __future__ import annotations

from django.contrib import admin

from apps.review.models import ReviewSession


@admin.register(ReviewSession)
class ReviewSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "status", "tier", "score_total", "product_route",
        "license_pathway", "nda_recommended", "created_at",
    )
    list_filter = ("status", "tier", "product_route", "nda_recommended", "created_at")
    search_fields = ("id", "client_id", "prompt")
    readonly_fields = (
        "id", "visitor_session", "client_id", "visitor_type", "status",
        "prompt", "pressure_areas", "environment", "nda_recommended", "nda_signals",
        "answers", "score_breakdown", "score_total", "tier", "product_route",
        "license_pathway", "placeholder_lead_id", "created_at", "updated_at",
    )

    fieldsets = (
        (None, {"fields": ("id", "status", "visitor_session", "client_id", "visitor_type")}),
        ("Prompt", {"fields": ("prompt", "pressure_areas", "environment", "nda_recommended", "nda_signals")}),
        ("Qualification", {"fields": ("answers", "score_breakdown", "score_total", "tier", "product_route", "license_pathway", "placeholder_lead_id")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
