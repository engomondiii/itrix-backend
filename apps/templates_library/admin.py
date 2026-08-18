"""Admin for the message / document templates library."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, badge, pretty_json, truncate
from apps.templates_library.models import Template


@admin.register(Template)
class TemplateAdmin(ItrixModelAdmin):
    list_display = ("name", "kind_col", "body_col", "updated_at")
    list_filter = ("kind",)
    search_fields = ("name", "body")
    ordering = ("kind", "name")
    readonly_fields = ("id", "created_at", "updated_at", "variables_pretty")
    fieldsets = (
        (None, {"fields": (("kind", "name"),)}),
        ("Body", {"fields": ("body",)}),
        ("Variables", {"fields": ("variables", "variables_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        return badge(obj.kind, "info")

    @admin.display(description="Body")
    def body_col(self, obj):
        return truncate(obj.body, 100)

    @admin.display(description="Variables (rendered)")
    def variables_pretty(self, obj):
        return pretty_json(obj.variables)
