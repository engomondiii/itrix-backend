"""Admin for NDA records."""

from __future__ import annotations

from django.contrib import admin

from apps.nda.models import NDARecord


@admin.register(NDARecord)
class NDARecordAdmin(admin.ModelAdmin):
    list_display = ("id", "lead_name", "status", "requested_at", "signed_at")
    list_filter = ("status",)
    search_fields = ("lead_name", "company")
