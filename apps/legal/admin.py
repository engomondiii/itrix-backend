"""
Admin for assent records.

READ-ONLY, entirely. An assent record is evidence. An admin who could edit
one could rewrite what a customer agreed to, which would make every record
in the table worth nothing — the value of the evidence is that nobody can
change it after the fact, including us. Nobody can delete one either.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin, badge, bullet_list, pretty_json
from apps.legal.models import AssentRecord


@admin.register(AssentRecord)
class AssentRecordAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "client_email_at_assent", "client", "path_col", "instruments_col", "accepted_at_client", "ip_address")
    list_filter = ("path", "created_at")
    search_fields = ("client_email_at_assent", "client__email", "client__organization", "ip_address")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("client",)
    readonly_fields = ("instruments_pretty", "instruments_col")
    fieldsets = (
        ("Who", {"fields": (("client", "client_email_at_assent"), "path")}),
        ("What was shown", {"fields": ("instruments_col", "instruments_pretty")}),
        ("When / where", {"fields": (("accepted_at_client", "created_at"), ("ip_address",), "user_agent")}),
        ("Record", {"fields": ("id", "updated_at")}),
    )

    @admin.display(description="Path", ordering="path")
    def path_col(self, obj):
        return badge(obj.path, "info")

    @admin.display(description="Instruments")
    def instruments_col(self, obj):
        return bullet_list(f"{slug} · v{obj.version_of(slug) or '?'}" for slug in obj.accepted_slugs)

    @admin.display(description="Instruments (raw)")
    def instruments_pretty(self, obj):
        return pretty_json(obj.instruments)
