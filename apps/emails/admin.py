"""Admin for email logs (read-only delivery audit)."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, badge, pretty_json, truncate
from apps.emails.models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "kind_col", "to_email", "subject_col", "status_col", "lead", "scheduled_at", "error_col")
    list_filter = ("kind", "status", ("lead", admin.EmptyFieldListFilter))
    search_fields = ("to_email", "from_email", "subject", "body", "provider_message_id", "lead__company", "lead__email")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead",)
    readonly_fields = ("cc_pretty", "attachments_pretty")
    fieldsets = (
        ("Envelope", {"fields": (("kind", "status"), ("from_email", "to_email"), "cc_pretty", ("lead", "scheduled_at"), "id")}),
        ("Message", {"fields": ("subject", "body", "attachments_pretty")}),
        ("Provider", {"fields": ("provider_message_id", "error")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        return badge(obj.kind, "info")

    @admin.display(description="Subject", ordering="subject")
    def subject_col(self, obj):
        return truncate(obj.subject, 70)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Error")
    def error_col(self, obj):
        return truncate(obj.error, 50)

    @admin.display(description="CC")
    def cc_pretty(self, obj):
        return pretty_json(obj.cc)

    @admin.display(description="Attachments")
    def attachments_pretty(self, obj):
        return pretty_json(obj.attachments)
