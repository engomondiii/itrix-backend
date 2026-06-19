"""Admin for NDA records."""

from __future__ import annotations

from django.contrib import admin

from apps.nda.models import NDARecord


@admin.register(NDARecord)
class NDARecordAdmin(admin.ModelAdmin):
    list_display = ("id", "lead_name", "status", "doc_type", "requested_at", "sent_at", "signed_at")
    list_filter = ("status", "doc_type")
    search_fields = ("lead_name", "company", "signer_name", "signer_email")
