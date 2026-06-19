"""Admin for email logs (read-only audit)."""

from __future__ import annotations

from django.contrib import admin

from apps.emails.models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "to_email", "subject", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("to_email", "subject", "body")
    readonly_fields = ("kind", "to_email", "from_email", "subject", "body", "status", "error", "provider_message_id", "cc", "attachments", "scheduled_at", "lead", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
