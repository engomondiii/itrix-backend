"""Admin for clients + credentials + consumed invites."""

from __future__ import annotations

from django.contrib import admin

from apps.clients.models import Client, ClientCredential
from apps.clients.models_consumed import ConsumedInvite


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "full_name", "organization", "nda_signed", "is_active", "created_at")
    list_filter = ("nda_signed", "is_active")
    search_fields = ("email", "full_name", "organization", "lead__id")
    readonly_fields = ("id", "lead", "created_at", "updated_at", "last_login_at")


@admin.register(ClientCredential)
class ClientCredentialAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "has_password", "set_password_expires_at")
    readonly_fields = ("id", "client", "password_hash", "created_at", "updated_at")

    def has_password(self, obj) -> bool:
        return obj.has_password

    has_password.boolean = True  # type: ignore[attr-defined]


@admin.register(ConsumedInvite)
class ConsumedInviteAdmin(admin.ModelAdmin):
    list_display = ("id", "nonce", "lead_id", "created_at")
    search_fields = ("nonce", "lead_id")
    readonly_fields = ("id", "nonce", "lead_id", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False
