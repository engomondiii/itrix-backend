"""Admin for journey transitions (read-only audit trail)."""

from __future__ import annotations

from django.contrib import admin

from apps.journey.models import JourneyTransition


@admin.register(JourneyTransition)
class JourneyTransitionAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "from_state", "to_state", "event", "reveal", "created_at")
    list_filter = ("to_state", "event", "reveal")
    search_fields = ("lead__id", "lead__company", "lead__email")
    readonly_fields = (
        "id",
        "lead",
        "from_state",
        "to_state",
        "event",
        "reveal",
        "actor",
        "meta",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
