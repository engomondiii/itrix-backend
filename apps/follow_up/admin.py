"""Admin for follow-up tasks."""

from __future__ import annotations

from django.contrib import admin

from apps.follow_up.models import FollowUpTask


@admin.register(FollowUpTask)
class FollowUpTaskAdmin(admin.ModelAdmin):
    list_display = ("id", "lead_name", "tier", "status", "due_at", "owner", "breach_notified")
    list_filter = ("status", "tier", "breach_notified")
    search_fields = ("lead_name", "company")
    date_hierarchy = "due_at"
