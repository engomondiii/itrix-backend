"""Admin for follow-up tasks — the SLA queue."""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from apps.core.admin import ItrixModelAdmin, badge, tier_badge, truncate
from apps.follow_up.models import FollowUpTask


class OverdueFilter(admin.SimpleListFilter):
    title = "overdue"
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return (("yes", "Overdue"), ("no", "On time"))

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == "yes":
            return queryset.filter(status="pending", due_at__lt=now)
        if self.value() == "no":
            return queryset.exclude(status="pending", due_at__lt=now)
        return queryset


@admin.register(FollowUpTask)
class FollowUpTaskAdmin(ItrixModelAdmin):
    list_display = ("due_col", "lead_col", "company", "tier_col", "status_col", "owner", "snoozed_until", "breach_notified", "note_col")
    list_display_links = ("due_col", "lead_col")
    list_filter = ("status", OverdueFilter, "tier", "breach_notified", ("owner", admin.RelatedOnlyFieldListFilter))
    search_fields = ("lead_name", "company", "note", "lead__email", "owner__email", "owner__name")
    raw_id_fields = ("lead",)
    autocomplete_fields = ("owner",)
    date_hierarchy = "due_at"
    ordering = ("due_at",)
    list_select_related = ("owner", "lead")
    actions = ["mark_completed", "mark_dismissed"]
    fieldsets = (
        (None, {"fields": (("lead", "lead_name", "company"), ("tier", "owner"))}),
        ("Schedule", {"fields": (("due_at", "status"), ("snoozed_until", "completed_at"), "breach_notified")}),
        ("Note", {"fields": ("note",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Due", ordering="due_at")
    def due_col(self, obj):
        overdue = obj.status == "pending" and obj.effective_due < timezone.now()
        text = timezone.localtime(obj.effective_due).strftime("%d %b %Y %H:%M")
        return badge(text, "danger") if overdue else text

    @admin.display(description="Lead", ordering="lead_name")
    def lead_col(self, obj):
        return obj.lead_name or (obj.lead.company if obj.lead_id else "—")

    @admin.display(description="Tier", ordering="tier")
    def tier_col(self, obj):
        return tier_badge(obj.tier)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Note")
    def note_col(self, obj):
        return truncate(obj.note, 60)

    @admin.action(description="Mark selected tasks completed")
    def mark_completed(self, request, queryset):
        n = queryset.filter(status__in=("pending", "snoozed")).update(status="completed", completed_at=timezone.now())
        self.message_user(request, f"{n} task(s) marked completed.")

    @admin.action(description="Dismiss selected tasks")
    def mark_dismissed(self, request, queryset):
        n = queryset.filter(status__in=("pending", "snoozed")).update(status="dismissed")
        self.message_user(request, f"{n} task(s) dismissed.")
