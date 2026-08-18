"""Admin for metric snapshots (read-only history)."""

from __future__ import annotations

from django.contrib import admin

from apps.analytics.models import MetricSnapshot
from apps.core.admin import ReadOnlyAdmin, pretty_json


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(ReadOnlyAdmin):
    list_display = ("captured_for", "new_leads", "tier1_count", "tier2_count", "overdue_follow_ups", "created_at")
    date_hierarchy = "captured_for"
    ordering = ("-captured_for",)
    readonly_fields = ("payload_pretty",)
    fieldsets = (
        ("Snapshot", {"fields": ("captured_for", ("new_leads", "tier1_count", "tier2_count", "overdue_follow_ups"))}),
        ("Payload", {"fields": ("payload_pretty",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Payload")
    def payload_pretty(self, obj):
        return pretty_json(obj.payload)
