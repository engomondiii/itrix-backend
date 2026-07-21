"""Customer-success admin for the success team."""

from __future__ import annotations

from django.contrib import admin

from apps.customer_success.models import (
    ChangeLogEntry,
    DeploymentHealth,
    FeedbackPulse,
    Outcome,
    RelationshipTeamMember,
    ReleaseNote,
    SuccessPlan,
    SuccessPlanMilestone,
    SuccessReview,
    SupportRequest,
)


@admin.register(Outcome)
class OutcomeAdmin(admin.ModelAdmin):
    list_display = ("title", "client", "status", "owner_side", "target_date")
    list_filter = ("status", "owner_side")
    search_fields = ("title",)


@admin.register(SupportRequest)
class SupportRequestAdmin(admin.ModelAdmin):
    list_display = ("subject", "client", "status", "urgency", "blocking", "sla_due_at")
    list_filter = ("status", "urgency", "blocking")
    search_fields = ("subject", "body")


@admin.register(FeedbackPulse)
class FeedbackPulseAdmin(admin.ModelAdmin):
    """Success team only — this is where the score is legitimately visible."""

    list_display = ("client", "score", "wants_follow_up", "acknowledged_at", "created_at")
    list_filter = ("wants_follow_up", "score")


@admin.register(DeploymentHealth)
class DeploymentHealthAdmin(admin.ModelAdmin):
    list_display = ("client", "environment", "status", "version", "last_checked_at")
    list_filter = ("status",)


@admin.register(RelationshipTeamMember)
class RelationshipTeamMemberAdmin(admin.ModelAdmin):
    list_display = ("display_name", "client", "role", "is_primary")
    list_filter = ("role", "is_primary")


admin.site.register(SuccessPlan)
admin.site.register(SuccessPlanMilestone)
admin.site.register(ReleaseNote)
admin.site.register(ChangeLogEntry)
admin.site.register(SuccessReview)
