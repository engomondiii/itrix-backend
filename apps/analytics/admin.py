"""Admin for metric snapshots (read-only history)."""

from __future__ import annotations

from django.contrib import admin

from apps.analytics.models import MetricSnapshot


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = ("captured_for", "new_leads", "tier1_count", "tier2_count", "overdue_follow_ups")
    date_hierarchy = "captured_for"
    readonly_fields = ("captured_for", "new_leads", "tier1_count", "tier2_count", "overdue_follow_ups", "payload", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
