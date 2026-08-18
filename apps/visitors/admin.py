"""
Admin for visitor tracking (read-only operational visibility).

A visitor session is anonymous by design: what is stored is a client id, a
hashed IP, the rooms visited and the review sessions started. Nothing here
is editable.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, ReadOnlyTabularInline, badge, count_link, truncate
from apps.review.models import ReviewSession
from apps.visitors.models import RoomEntry, VisitorSession


class RoomEntryInline(ReadOnlyTabularInline):
    model = RoomEntry
    fields = ("created_at", "room", "visitor_type")
    ordering = ("-created_at",)
    verbose_name_plural = "Room entries"


class ReviewSessionInline(ReadOnlyTabularInline):
    model = ReviewSession
    fields = ("created_at", "status", "tier", "score_total", "product_route", "nda_recommended")
    ordering = ("-created_at",)
    verbose_name_plural = "Review sessions"


@admin.register(VisitorSession)
class VisitorSessionAdmin(ReadOnlyAdmin):
    list_display = ("client_id", "type_col", "landing_col", "referrer_col", "room_entry_count", "reviews_col", "created_at", "last_seen_at")
    list_filter = ("visitor_type", "created_at")
    search_fields = ("client_id", "id", "landing_path", "referrer")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    fieldsets = (
        ("Visitor", {"fields": (("client_id", "visitor_type"), ("landing_path", "referrer"), "user_agent", "ip_hash", "id")}),
        ("Activity", {"fields": (("room_entry_count", "last_seen_at"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [RoomEntryInline, ReviewSessionInline]

    @admin.display(description="Type", ordering="visitor_type")
    def type_col(self, obj):
        return badge(obj.visitor_type, "info" if obj.visitor_type != "unknown" else "muted")

    @admin.display(description="Landing", ordering="landing_path")
    def landing_col(self, obj):
        return truncate(obj.landing_path, 40)

    @admin.display(description="Referrer", ordering="referrer")
    def referrer_col(self, obj):
        return truncate(obj.referrer, 40)

    @admin.display(description="Reviews")
    def reviews_col(self, obj):
        return count_link(ReviewSession, obj.review_sessions.count(), visitor_session__id__exact=obj.pk)


@admin.register(RoomEntry)
class RoomEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "room_col", "visitor_type", "session")
    list_filter = ("room", "visitor_type", "created_at")
    search_fields = ("session__client_id", "session__id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("session",)

    @admin.display(description="Room", ordering="room")
    def room_col(self, obj):
        return badge(obj.room, "primary")
