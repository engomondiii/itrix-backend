"""Admin for in-app notifications."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ItrixModelAdmin, badge, truncate
from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(ItrixModelAdmin):
    list_display = ("created_at", "kind_col", "title", "body_col", "lead", "read")
    list_filter = ("kind", "read")
    search_fields = ("title", "body", "href", "lead__company", "lead__email")
    raw_id_fields = ("lead",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_editable = ("read",)
    list_select_related = ("lead",)
    actions = ["mark_read", "mark_unread"]
    fields = (("kind", "read"), "title", "body", ("href", "lead"), ("created_at", "updated_at"), "id")

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        tone = {
            "tier1_lead": "danger",
            "sla_breach": "danger",
            "escalation": "warning",
            "nda_signed": "success",
            "new_lead": "primary",
            "system": "muted",
        }.get(obj.kind, "muted")
        return badge(obj.kind, tone)

    @admin.display(description="Body")
    def body_col(self, obj):
        return truncate(obj.body, 80)

    @admin.action(description="Mark selected as read")
    def mark_read(self, request, queryset):
        self.message_user(request, f"{queryset.update(read=True)} marked read.")

    @admin.action(description="Mark selected as unread")
    def mark_unread(self, request, queryset):
        self.message_user(request, f"{queryset.update(read=False)} marked unread.")
