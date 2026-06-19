"""Admin for leads, notes, and activity."""

from __future__ import annotations

from django.contrib import admin

from apps.leads.models import Lead, LeadActivity, LeadMeeting, LeadNote


class LeadNoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0
    readonly_fields = ("body", "author", "author_name", "created_at")
    can_delete = False


class LeadMeetingInline(admin.TabularInline):
    model = LeadMeeting
    extra = 0
    readonly_fields = ("scheduled_at", "duration_mins", "attendee", "location", "notes", "booked_by", "booked_by_name", "created_at")
    can_delete = False


class LeadActivityInline(admin.TabularInline):
    model = LeadActivity
    extra = 0
    readonly_fields = ("type", "label", "by", "by_name", "created_at")
    can_delete = False


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("id", "company", "email", "tier", "score", "status", "product_route", "owner", "submitted_at")
    list_filter = ("tier", "status", "product_route", "commercial_path", "special_rights", "escalated")
    search_fields = ("company", "visitor_name", "email", "industry")
    readonly_fields = ("id", "review_session", "submitted_at", "created_at", "updated_at", "score_breakdown", "qualification")
    inlines = [LeadNoteInline, LeadMeetingInline, LeadActivityInline]
    date_hierarchy = "submitted_at"


@admin.register(LeadNote)
class LeadNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "author_name", "created_at")
    search_fields = ("body", "author_name")


@admin.register(LeadMeeting)
class LeadMeetingAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "scheduled_at", "duration_mins", "attendee", "booked_by_name", "created_at")
    search_fields = ("attendee", "location", "booked_by_name")


@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "type", "label", "by_name", "created_at")
    list_filter = ("type",)
