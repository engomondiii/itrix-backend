"""Admin for PoCs."""

from __future__ import annotations

from django.contrib import admin

from apps.pocs.models import PoC


@admin.register(PoC)
class PoCAdmin(admin.ModelAdmin):
    list_display = ("id", "lead_name", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("lead_name", "company")
