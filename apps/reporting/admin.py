"""Admin for monthly reports."""

from __future__ import annotations

from django.contrib import admin

from apps.reporting.models import MonthlyReport


@admin.register(MonthlyReport)
class MonthlyReportAdmin(admin.ModelAdmin):
    list_display = ("id", "month", "generated_at")
    search_fields = ("month",)
    readonly_fields = ("month", "sections", "generated_at", "created_at", "updated_at")
