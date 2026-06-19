"""Admin registrations for operator settings."""

from __future__ import annotations

from django.contrib import admin

from apps.settings.models import NotificationPreference, SlaThresholds


@admin.register(SlaThresholds)
class SlaThresholdsAdmin(admin.ModelAdmin):
    list_display = ("id", "tier1_hours", "tier2_hours", "tier3_hours", "tier4_hours", "updated_at")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "tier1", "sla", "nda", "weekly", "updated_at")
    search_fields = ("user__email", "user__name")
