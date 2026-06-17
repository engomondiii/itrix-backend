"""Admin for visitor tracking (read-only operational visibility)."""

from __future__ import annotations

from django.contrib import admin

from apps.visitors.models import RoomEntry, VisitorSession


class RoomEntryInline(admin.TabularInline):
    model = RoomEntry
    extra = 0
    readonly_fields = ("room", "visitor_type", "created_at")
    can_delete = False


@admin.register(VisitorSession)
class VisitorSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "client_id", "visitor_type", "room_entry_count", "created_at", "last_seen_at")
    list_filter = ("visitor_type", "created_at")
    search_fields = ("client_id", "id")
    readonly_fields = (
        "id", "client_id", "visitor_type", "referrer", "user_agent",
        "ip_hash", "landing_path", "room_entry_count", "created_at", "updated_at", "last_seen_at",
    )
    inlines = [RoomEntryInline]


@admin.register(RoomEntry)
class RoomEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "visitor_type", "session", "created_at")
    list_filter = ("room", "visitor_type", "created_at")
    readonly_fields = ("id", "session", "room", "visitor_type", "created_at", "updated_at")
