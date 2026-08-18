"""Admin registrations for operator settings."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, bool_badge
from apps.settings.models import NotificationPreference, SlaThresholds


@admin.register(SlaThresholds)
class SlaThresholdsAdmin(ItrixModelAdmin):
    """Singleton: one org-wide row. Adding a second is blocked once one exists."""

    list_display = ("__str__", "tier1_hours", "tier2_hours", "tier3_hours", "tier4_hours", "updated_at")
    fields = (("tier1_hours", "tier2_hours"), ("tier3_hours", "tier4_hours"), ("created_at", "updated_at"), "id")

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SlaThresholds.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(ItrixModelAdmin):
    list_display = ("user", "tier1_col", "sla_col", "nda_col", "weekly_col", "updated_at")
    list_filter = ("tier1", "sla", "nda", "weekly")
    search_fields = ("user__email", "user__name")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    fields = ("user", ("tier1", "sla", "nda", "weekly"), ("created_at", "updated_at"), "id")

    @admin.display(description="Tier-1 alerts", ordering="tier1")
    def tier1_col(self, obj):
        return bool_badge(obj.tier1, "on", "off")

    @admin.display(description="SLA alerts", ordering="sla")
    def sla_col(self, obj):
        return bool_badge(obj.sla, "on", "off")

    @admin.display(description="NDA alerts", ordering="nda")
    def nda_col(self, obj):
        return bool_badge(obj.nda, "on", "off")

    @admin.display(description="Weekly digest", ordering="weekly")
    def weekly_col(self, obj):
        return bool_badge(obj.weekly, "on", "off")
