"""
Customer-success admin (State 10) for the success team.

Everything here is scoped to a Client. The plan carries its milestones inline;
support requests show SLA state at a glance; the feedback pulse score is
visible ONLY here (it is private customer feedback and never surfaces on
the client plane).
"""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from apps.core.admin import (
    EditableTabularInline,
    ItrixModelAdmin,
    badge,
    bool_badge,
    pretty_json,
    truncate,
)
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


class SuccessPlanMilestoneInline(EditableTabularInline):
    model = SuccessPlanMilestone
    fields = ("horizon", "title", "status", "owner_side", "owner_name", "needs_customer_action", "due_on", "completed_at")
    ordering = ("horizon", "due_on")
    verbose_name_plural = "30 / 60 / 90 milestones"


@admin.register(SuccessPlan)
class SuccessPlanAdmin(ItrixModelAdmin):
    list_display = ("title", "client", "is_active", "starts_on", "reviewed_at", "milestone_count", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "summary", "client__email", "client__organization")
    raw_id_fields = ("client",)
    fieldsets = (
        (None, {"fields": (("client", "is_active"), "title", "summary", ("starts_on", "reviewed_at"))}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )
    inlines = [SuccessPlanMilestoneInline]

    @admin.display(description="Milestones")
    def milestone_count(self, obj):
        return obj.milestones.count()


@admin.register(SuccessPlanMilestone)
class SuccessPlanMilestoneAdmin(ItrixModelAdmin):
    list_display = ("title", "plan", "horizon_col", "status_col", "owner_side", "owner_name", "needs_customer_action", "due_on", "completed_at")
    list_filter = ("horizon", "status", "owner_side", "needs_customer_action")
    search_fields = ("title", "plan__title", "plan__client__email", "plan__client__organization")
    raw_id_fields = ("plan",)
    ordering = ("plan", "horizon", "due_on")

    @admin.display(description="Horizon", ordering="horizon")
    def horizon_col(self, obj):
        return badge(f"{obj.horizon}d", "info")

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)


@admin.register(Outcome)
class OutcomeAdmin(ItrixModelAdmin):
    list_display = ("title", "client", "status_col", "owner_side", "owner_name", "measure", "target_date", "achieved_at")
    list_filter = ("status", "owner_side")
    search_fields = ("title", "description", "measure", "client__email", "client__organization")
    raw_id_fields = ("client",)
    date_hierarchy = "target_date"
    fieldsets = (
        (None, {"fields": (("client", "status"), "title", "description", "measure")}),
        ("Ownership", {"fields": (("owner_side", "owner_name"),)}),
        ("Progress", {"fields": (("target_date", "achieved_at"), "status_note")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)


@admin.register(SupportRequest)
class SupportRequestAdmin(ItrixModelAdmin):
    list_display = ("subject_col", "client", "status_col", "urgency_col", "blocking_col", "owner", "sla_col", "first_response_at", "created_at")
    list_display_links = ("subject_col",)
    list_filter = ("status", "urgency", "blocking", ("owner", admin.RelatedOnlyFieldListFilter), "customer_confirmed_resolved")
    search_fields = ("subject", "body", "thread_id", "client__email", "client__organization", "owner_name")
    raw_id_fields = ("client",)
    autocomplete_fields = ("owner",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": (("client", "thread_id"), "subject", "body")}),
        ("Triage", {"fields": (("status", "urgency", "blocking"), ("owner", "owner_name"))}),
        ("SLA", {"fields": (("sla_due_at", "first_response_at", "resolved_at"),)}),
        ("Resolution", {"fields": ("resolution_note", "customer_confirmed_resolved")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Subject", ordering="subject")
    def subject_col(self, obj):
        return truncate(obj.subject, 70)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Urgency", ordering="urgency")
    def urgency_col(self, obj):
        return badge(obj.urgency)

    @admin.display(description="Blocking", ordering="blocking")
    def blocking_col(self, obj):
        return badge("blocking", "danger") if obj.blocking else badge("—", "muted")

    @admin.display(description="SLA", ordering="sla_due_at")
    def sla_col(self, obj):
        if not obj.sla_due_at:
            return "—"
        if obj.resolved_at:
            return badge("met" if obj.resolved_at <= obj.sla_due_at else "missed", "success" if obj.resolved_at <= obj.sla_due_at else "danger")
        overdue = obj.sla_due_at < timezone.now()
        return badge("overdue" if overdue else obj.sla_due_at.strftime("%d %b %H:%M"), "danger" if overdue else "info")


@admin.register(FeedbackPulse)
class FeedbackPulseAdmin(ItrixModelAdmin):
    """Success team only — this is the one place the score is legitimately visible."""

    list_display = ("created_at", "client", "score_col", "comment_col", "wants_follow_up", "acknowledged_at", "acknowledged_by")
    list_filter = ("wants_follow_up", "score", ("acknowledged_at", admin.EmptyFieldListFilter))
    search_fields = ("comment", "client__email", "client__organization")
    raw_id_fields = ("client",)
    autocomplete_fields = ("acknowledged_by",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    fields = (("client", "score", "wants_follow_up"), "comment", ("acknowledged_at", "acknowledged_by"), ("created_at", "updated_at"), "id")

    @admin.display(description="Score", ordering="score")
    def score_col(self, obj):
        if obj.score is None:
            return "—"
        tone = "danger" if obj.is_negative else ("success" if obj.score >= 4 else "warning")
        return badge(f"{obj.score}/5", tone)

    @admin.display(description="Comment")
    def comment_col(self, obj):
        return truncate(obj.comment, 90)


@admin.register(DeploymentHealth)
class DeploymentHealthAdmin(ItrixModelAdmin):
    list_display = ("client", "environment", "status_col", "version", "last_checked_at", "updated_at")
    list_filter = ("status", "environment")
    search_fields = ("environment", "version", "client__email", "client__organization")
    raw_id_fields = ("client",)
    ordering = ("client", "environment")
    fields = (("client", "environment"), ("status", "version", "last_checked_at"), "incident_note", "known_limitations", ("created_at", "updated_at"), "id")

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)


@admin.register(RelationshipTeamMember)
class RelationshipTeamMemberAdmin(ItrixModelAdmin):
    list_display = ("display_name", "client", "role_col", "is_primary", "user", "contact_email", "helps_with")
    list_filter = ("role", "is_primary")
    search_fields = ("display_name", "contact_email", "helps_with", "client__email", "client__organization", "user__email")
    raw_id_fields = ("client",)
    autocomplete_fields = ("user",)
    ordering = ("client", "role", "-is_primary")

    @admin.display(description="Role", ordering="role")
    def role_col(self, obj):
        return badge(obj.role, "info")


@admin.register(ReleaseNote)
class ReleaseNoteAdmin(ItrixModelAdmin):
    list_display = ("version", "title", "released_at", "customer_scope", "published_col")
    list_filter = ("is_published", "customer_scope")
    search_fields = ("version", "title", "body")
    date_hierarchy = "released_at"
    ordering = ("-released_at",)
    fields = (("version", "released_at"), "title", "body", ("customer_scope", "is_published"), ("created_at", "updated_at"), "id")

    @admin.display(description="Published", ordering="is_published")
    def published_col(self, obj):
        return bool_badge(obj.is_published, "published", "draft")


@admin.register(ChangeLogEntry)
class ChangeLogEntryAdmin(ItrixModelAdmin):
    list_display = ("occurred_at", "client", "kind_col", "title", "surfaced_at")
    list_filter = ("kind", ("surfaced_at", admin.EmptyFieldListFilter))
    search_fields = ("title", "detail", "client__email", "client__organization")
    raw_id_fields = ("client",)
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)
    fields = (("client", "kind"), "title", "detail", ("occurred_at", "surfaced_at"), ("created_at", "updated_at"), "id")

    @admin.display(description="Kind", ordering="kind")
    def kind_col(self, obj):
        return badge(obj.kind)


@admin.register(SuccessReview)
class SuccessReviewAdmin(ItrixModelAdmin):
    list_display = ("scheduled_at", "client", "state_col", "completed_at")
    list_filter = (("completed_at", admin.EmptyFieldListFilter),)
    search_fields = ("notes", "client__email", "client__organization")
    raw_id_fields = ("client",)
    date_hierarchy = "scheduled_at"
    ordering = ("scheduled_at",)
    readonly_fields = ("agenda_pretty",)
    fields = (("client", "scheduled_at", "completed_at"), "agenda", "agenda_pretty", "notes", ("created_at", "updated_at"), "id")

    @admin.display(description="State")
    def state_col(self, obj):
        if obj.completed_at:
            return badge("completed", "success")
        return badge("upcoming" if obj.scheduled_at >= timezone.now() else "overdue", "info" if obj.scheduled_at >= timezone.now() else "warning")

    @admin.display(description="Agenda (rendered)")
    def agenda_pretty(self, obj):
        return pretty_json(obj.agenda)
