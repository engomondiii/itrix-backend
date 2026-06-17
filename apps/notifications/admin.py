"""Admin for notifications."""

from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "title", "read", "created_at")
    list_filter = ("kind", "read")
    search_fields = ("title", "body")
