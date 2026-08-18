"""
Admin for review sessions (operational visibility for the team).

A review session is the anonymous visitor's qualification run. It is
system-owned and read-only here; the page shows the prompt, the scoring,
and the leads / generation logs that came out of it.
"""

from __future__ import annotations

from django.contrib import admin

from apps.ai_engine.models import GenerationLog
from apps.core.admin import (
    ReadOnlyAdmin,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    link_to,
    pretty_json,
    short_id,
    tier_badge,
    truncate,
)
from apps.leads.models import Lead
from apps.review.models import ReviewSession


class ReviewLeadInline(ReadOnlyTabularInline):
    model = Lead
    fk_name = "review_session"
    fields = ("company", "email", "tier", "score", "status", "journey_state", "submitted_at")
    verbose_name_plural = "Leads from this session"


class GenerationLogInline(ReadOnlyTabularInline):
    model = GenerationLog
    fk_name = "review_session"
    fields = ("created_at", "product_route", "used_ai", "chunk_count", "ok", "error")
    ordering = ("-created_at",)
    verbose_name_plural = "Generation logs"


@admin.register(ReviewSession)
class ReviewSessionAdmin(ReadOnlyAdmin):
    list_display = (
        "short_id_col",
        "status_col",
        "visitor_type",
        "tier_col",
        "score_total",
        "product_route",
        "license_pathway",
        "nda_col",
        "prompt_col",
        "stop_reason",
        "created_at",
    )
    list_display_links = ("short_id_col",)
    list_filter = ("status", "tier", "product_route", "license_pathway", "nda_recommended", "visitor_type", "stop_reason")
    search_fields = ("id", "client_id", "prompt", "environment")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "visitor_session_link",
        "pressure_areas_pretty",
        "nda_signals_pretty",
        "answers_pretty",
        "score_breakdown_pretty",
    )
    fieldsets = (
        (
            "Session",
            {"fields": (("status", "stop_reason"), ("visitor_session", "visitor_session_link"), ("client_id", "visitor_type"), "id")},
        ),
        ("Prompt", {"fields": ("prompt", "environment", "pressure_areas_pretty", ("nda_recommended",), "nda_signals_pretty")}),
        (
            "Qualification",
            {
                "fields": (
                    ("score_total", "tier"),
                    ("product_route", "license_pathway"),
                    "answers_pretty",
                    "score_breakdown_pretty",
                    "placeholder_lead_id",
                )
            },
        ),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [ReviewLeadInline, GenerationLogInline]

    @admin.display(description="Session", ordering="id")
    def short_id_col(self, obj):
        return short_id(obj.id)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Tier", ordering="tier")
    def tier_col(self, obj):
        return tier_badge(obj.tier)

    @admin.display(description="NDA", ordering="nda_recommended")
    def nda_col(self, obj):
        return bool_badge(obj.nda_recommended, "recommended", "—")

    @admin.display(description="Prompt")
    def prompt_col(self, obj):
        return truncate(obj.prompt, 80)

    @admin.display(description="Visitor session")
    def visitor_session_link(self, obj):
        return link_to(obj.visitor_session)

    @admin.display(description="Pressure areas")
    def pressure_areas_pretty(self, obj):
        return pretty_json(obj.pressure_areas)

    @admin.display(description="NDA signals")
    def nda_signals_pretty(self, obj):
        return pretty_json(obj.nda_signals)

    @admin.display(description="Answers")
    def answers_pretty(self, obj):
        return pretty_json(obj.answers)

    @admin.display(description="Score breakdown")
    def score_breakdown_pretty(self, obj):
        return pretty_json(obj.score_breakdown)
