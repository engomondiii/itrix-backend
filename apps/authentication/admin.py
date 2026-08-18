"""
Django admin for the internal team ``User`` model.

Built on Django's ``UserAdmin`` so password handling (hashing on create, the
change-password link) keeps working; adds the operator's notification
preferences and a glance at their workload (owned leads / follow-ups) so a
team lead can see what a person is carrying from their record.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.db.models import Count, Q
from django.utils.html import format_html

from apps.authentication.models import User
from apps.core.admin import badge, count_link
from apps.follow_up.models import FollowUpTask
from apps.leads.models import Lead
from apps.settings.models import NotificationPreference


class NotificationPreferenceInline(admin.StackedInline):
    model = NotificationPreference
    fields = (("tier1", "sla", "nda", "weekly"),)
    can_delete = False
    extra = 0
    max_num = 1
    verbose_name_plural = "Notification preferences"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    ordering = ("name", "email")
    list_display = ("email", "name", "role_col", "team_role", "open_leads_col", "open_tasks_col", "is_active", "is_staff", "last_login")
    list_filter = ("role", "team_role", "is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "name")
    readonly_fields = ("id", "created_at", "updated_at", "last_login", "avatar_preview", "workload")
    filter_horizontal = ("groups", "user_permissions")
    save_on_top = True
    list_per_page = 50
    inlines = [NotificationPreferenceInline]

    fieldsets = (
        (None, {"fields": (("email", "password"), "id")}),
        ("Profile", {"fields": ("name", ("avatar_url", "avatar_preview"))}),
        ("Roles", {"fields": (("role", "team_role"),)}),
        ("Workload", {"fields": ("workload",)}),
        (
            "Permissions",
            {"fields": (("is_active", "is_staff", "is_superuser"), "groups", "user_permissions")},
        ),
        ("Timestamps", {"fields": (("last_login", "created_at", "updated_at"),)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", ("role", "team_role"), "password1", "password2", ("is_active", "is_staff")),
            },
        ),
    )

    def get_queryset(self, request):
        open_statuses = ("New", "Contacted", "Qualifying", "Meeting Booked", "NDA", "Evaluation", "PoC", "Negotiation", "Nurture")
        return (
            super()
            .get_queryset(request)
            .annotate(
                _open_leads=Count("owned_leads", filter=Q(owned_leads__status__in=open_statuses), distinct=True),
                _open_tasks=Count("follow_up_tasks", filter=Q(follow_up_tasks__status="pending"), distinct=True),
            )
        )

    @admin.display(description="Role", ordering="role")
    def role_col(self, obj):
        tone = {"ADMIN": "primary", "SPECIALIST": "info", "ASSESSMENT": "info", "VIEWER": "muted"}.get(obj.role, "muted")
        return badge(obj.role, tone)

    @admin.display(description="Open leads", ordering="_open_leads")
    def open_leads_col(self, obj):
        return count_link(Lead, getattr(obj, "_open_leads", 0), owner__id__exact=obj.pk)

    @admin.display(description="Pending tasks", ordering="_open_tasks")
    def open_tasks_col(self, obj):
        return count_link(FollowUpTask, getattr(obj, "_open_tasks", 0), owner__id__exact=obj.pk, status__exact="pending")

    @admin.display(description="Preview")
    def avatar_preview(self, obj):
        if not obj.avatar_url:
            return "—"
        return format_html('<img src="{}" alt="" style="height:48px;width:48px;border-radius:12px;object-fit:cover">', obj.avatar_url)

    @admin.display(description="Owned")
    def workload(self, obj):
        if not obj.pk:
            return "—"
        leads = Lead.objects.filter(owner=obj).count()
        tasks = FollowUpTask.objects.filter(owner=obj, status="pending").count()
        return format_html(
            "{} owned leads &nbsp;·&nbsp; {} pending follow-ups",
            count_link(Lead, leads, owner__id__exact=obj.pk),
            count_link(FollowUpTask, tasks, owner__id__exact=obj.pk, status__exact="pending"),
        )


# Groups are rarely used here (roles live on the User), but keep them reachable
# and searchable so autocomplete / permissions management works.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    filter_horizontal = ("permissions",)
    ordering = ("name",)
