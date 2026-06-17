"""Admin for templates."""

from __future__ import annotations

from django.contrib import admin

from apps.templates_library.models import Template


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "name", "updated_at")
    list_filter = ("kind",)
    search_fields = ("name", "body")
    readonly_fields = ("variables",)
