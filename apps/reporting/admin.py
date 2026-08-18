"""Admin for generated monthly reports (read-only)."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, pretty_json
from apps.reporting.models import MonthlyReport


@admin.register(MonthlyReport)
class MonthlyReportAdmin(ReadOnlyAdmin):
    list_display = ("month", "generated_at", "section_count")
    search_fields = ("month",)
    ordering = ("-month",)
    readonly_fields = ("sections_pretty",)
    fieldsets = (
        (None, {"fields": (("month", "generated_at"), "id")}),
        ("Sections", {"fields": ("sections_pretty",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Sections")
    def section_count(self, obj):
        sections = obj.sections
        return len(sections) if isinstance(sections, (list, dict)) else "—"

    @admin.display(description="Sections (rendered)")
    def sections_pretty(self, obj):
        return pretty_json(obj.sections)
