from __future__ import annotations

from django.contrib import admin

from apps.legal.models import AssentRecord


@admin.register(AssentRecord)
class AssentRecordAdmin(admin.ModelAdmin):
    """
    READ-ONLY, entirely.

    An assent record is evidence. An admin who could edit one could rewrite what a customer
    agreed to, which would make every record in the table worth nothing — the value of the
    evidence is that nobody can change it after the fact, including us.
    """

    list_display = ("client_email_at_assent", "path", "created_at")
    list_filter = ("path", "created_at")
    search_fields = ("client_email_at_assent",)
    readonly_fields = tuple(f.name for f in AssentRecord._meta.fields) + ("instruments",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
