"""Admin for claim cards + approval requests."""

from __future__ import annotations

from django.contrib import admin

from apps.governance.models import ApprovalRequest, ClaimCard


@admin.register(ClaimCard)
class ClaimCardAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "claim_level", "is_active", "owner", "updated_at")
    list_filter = ("claim_level", "is_active")
    search_fields = ("key", "title", "approved_wording")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "claim_level", "status", "agent_key", "lead", "first_approver", "second_approver", "created_at")
    list_filter = ("status", "claim_level")
    search_fields = ("message_id", "conversation_id", "lead__id")
    readonly_fields = tuple(f.name for f in ApprovalRequest._meta.fields)
    date_hierarchy = "created_at"
