"""Admin for NDA records."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, badge, pretty_json
from apps.nda.models import NDARecord


@admin.register(NDARecord)
class NDARecordAdmin(ItrixModelAdmin):
    list_display = ("lead_name", "company", "status_col", "doc_type", "signer_name", "requested_at", "sent_at", "signed_at")
    list_filter = ("status", "doc_type")
    search_fields = ("lead_name", "company", "signer_name", "signer_email", "lead__email")
    raw_id_fields = ("lead",)
    date_hierarchy = "requested_at"
    ordering = ("-requested_at",)
    readonly_fields = ("id", "requested_at", "created_at", "updated_at", "checklist_pretty")
    fieldsets = (
        (None, {"fields": (("lead", "lead_name", "company"), ("status", "doc_type"))}),
        ("Signer", {"fields": (("signer_name", "signer_email"),)}),
        ("Lifecycle", {"fields": (("requested_at", "sent_at", "signed_at"), "decline_reason")}),
        ("Checklist", {"fields": ("checklist", "checklist_pretty")}),
        ("Document body", {"fields": ("body",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Checklist (rendered)")
    def checklist_pretty(self, obj):
        return pretty_json(obj.checklist)
