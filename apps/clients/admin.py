"""
Admin for the client identity plane: accounts, credentials, tokens, invites.

The Client is the second hub (after Lead): the customer-success domain,
threads, conversations and legal assent all hang off it, so its change page
carries those as inline tabs. Secrets never render — credential hashes and
token hashes are excluded outright, and the credential inline shows only
*whether* a password is set.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from apps.clients.models import (
    Client,
    ClientCredential,
    ClientTeamInvite,
    ConsumedInvite,
    EmailVerificationToken,
    PasswordResetToken,
)
from apps.core.admin import (
    AppendOnlyAdmin,
    EditableTabularInline,
    ItrixModelAdmin,
    ReadOnlyAdmin,
    ReadOnlyStackedInline,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    link_to,
    pretty_json,
    truncate,
)
from apps.customer_success.models import (
    DeploymentHealth,
    Outcome,
    RelationshipTeamMember,
    SuccessPlan,
    SupportRequest,
)
from apps.legal.models import AssentRecord

# ─────────────────────────────────────────────────────────────────────────────
# Inlines
# ─────────────────────────────────────────────────────────────────────────────


class ClientCredentialInline(ReadOnlyStackedInline):
    model = ClientCredential
    fields = ("has_password_col", "set_password_expires_at", "updated_at")
    readonly_fields = ("has_password_col",)
    verbose_name_plural = "Credential"

    @admin.display(description="Password set", boolean=True)
    def has_password_col(self, obj):
        return obj.has_password


class ClientTeamInviteInline(EditableTabularInline):
    model = ClientTeamInvite
    fields = ("email", "status", "created_at")
    readonly_fields = ("created_at",)
    verbose_name_plural = "Team invites"


class PasswordResetTokenInline(ReadOnlyTabularInline):
    model = PasswordResetToken
    fields = ("created_at", "expires_at", "consumed_at", "invalidated_at", "requested_ip")
    ordering = ("-created_at",)
    verbose_name_plural = "Password resets"


class EmailVerificationTokenInline(ReadOnlyTabularInline):
    model = EmailVerificationToken
    fields = ("created_at", "email", "expires_at", "consumed_at", "invalidated_at", "requested_ip")
    ordering = ("-created_at",)
    verbose_name_plural = "Email verifications"


class AssentRecordInline(ReadOnlyTabularInline):
    model = AssentRecord
    fields = ("created_at", "path", "client_email_at_assent", "accepted_at_client", "ip_address")
    ordering = ("-created_at",)
    verbose_name_plural = "Assent records"


class RelationshipTeamInline(EditableTabularInline):
    model = RelationshipTeamMember
    fields = ("display_name", "role", "user", "helps_with", "contact_email", "is_primary")
    autocomplete_fields = ("user",)
    verbose_name_plural = "Relationship team"


class OutcomeInline(EditableTabularInline):
    model = Outcome
    fields = ("title", "status", "owner_side", "owner_name", "target_date", "achieved_at")
    verbose_name_plural = "Outcomes"


class SuccessPlanInline(ReadOnlyTabularInline):
    model = SuccessPlan
    fields = ("title", "is_active", "starts_on", "reviewed_at")
    verbose_name_plural = "Success plans"


class DeploymentHealthInline(EditableTabularInline):
    model = DeploymentHealth
    fields = ("environment", "status", "version", "last_checked_at")
    verbose_name_plural = "Deployments"


class SupportRequestInline(ReadOnlyTabularInline):
    model = SupportRequest
    fields = ("created_at", "subject", "status", "urgency", "blocking", "owner_name", "sla_due_at")
    ordering = ("-created_at",)
    verbose_name_plural = "Support requests"


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Client)
class ClientAdmin(ItrixModelAdmin):
    list_display = (
        "email",
        "full_name",
        "organization",
        "origin_col",
        "verified_col",
        "nda_col",
        "contract_state",
        "health_col",
        "is_active",
        "last_login_at",
        "created_at",
    )
    list_filter = (
        "account_origin",
        "is_active",
        "nda_signed",
        "contract_state",
        "customer_health",
        ("email_verified_at", admin.EmptyFieldListFilter),
    )
    search_fields = ("email", "full_name", "organization", "lead__company", "lead__email", "id")
    raw_id_fields = ("lead",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "lead_link",
        "created_at",
        "updated_at",
        "last_login_at",
        "email_verified_at",
        "password_changed_at",
        "first_payment_recorded_at",
        "notification_prefs_pretty",
    )
    fieldsets = (
        (
            "Account",
            {
                "fields": (
                    ("email", "full_name"),
                    ("organization", "role"),
                    ("account_origin", "is_active"),
                    "lead",
                    "lead_link",
                    "id",
                )
            },
        ),
        (
            "Verification & security",
            {
                "fields": (
                    ("email_verified_at", "password_changed_at"),
                    ("last_login_at",),
                )
            },
        ),
        (
            "NDA & contract",
            {
                "fields": (
                    ("nda_signed", "nda_requested_at", "nda_signed_at"),
                    ("contract_state", "first_payment_recorded_at"),
                    "customer_health",
                )
            },
        ),
        ("Preferences", {"fields": ("notification_prefs_pretty",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )
    inlines = [
        ClientCredentialInline,
        ClientTeamInviteInline,
        RelationshipTeamInline,
        OutcomeInline,
        SuccessPlanInline,
        DeploymentHealthInline,
        SupportRequestInline,
        AssentRecordInline,
        EmailVerificationTokenInline,
        PasswordResetTokenInline,
    ]

    @admin.display(description="Origin", ordering="account_origin")
    def origin_col(self, obj):
        return badge(obj.account_origin, "info" if obj.account_origin == "invited" else "muted")

    @admin.display(description="Verified", ordering="email_verified_at", boolean=True)
    def verified_col(self, obj):
        return obj.email_verified_at is not None

    @admin.display(description="NDA", ordering="nda_signed")
    def nda_col(self, obj):
        return bool_badge(obj.nda_signed, "signed", "not signed")

    @admin.display(description="Health", ordering="customer_health")
    def health_col(self, obj):
        return badge(obj.customer_health)

    @admin.display(description="Open lead")
    def lead_link(self, obj):
        return link_to(obj.lead)

    @admin.display(description="Notification prefs")
    def notification_prefs_pretty(self, obj):
        return pretty_json(obj.notification_prefs)


# ─────────────────────────────────────────────────────────────────────────────
# Credentials & tokens — secrets are never shown
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(ClientCredential)
class ClientCredentialAdmin(ReadOnlyAdmin):
    list_display = ("client", "has_password_col", "set_password_expires_at", "updated_at")
    search_fields = ("client__email", "client__full_name")
    exclude = ("password_hash", "set_password_token")
    readonly_fields = ("has_password_col",)
    fields = ("client", "has_password_col", "set_password_expires_at", ("created_at", "updated_at"))

    @admin.display(description="Password set", boolean=True)
    def has_password_col(self, obj):
        return obj.has_password


class _TokenAdmin(ReadOnlyAdmin):
    """Shared shape for the two hashed-token tables."""

    list_filter = (
        ("consumed_at", admin.EmptyFieldListFilter),
        ("invalidated_at", admin.EmptyFieldListFilter),
    )
    search_fields = ("client__email", "client__full_name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("state_col",)

    @admin.display(description="State")
    def state_col(self, obj):
        if obj.consumed_at:
            return badge("consumed", "success")
        if obj.invalidated_at:
            return badge("invalidated", "danger")
        if obj.expires_at and obj.expires_at < timezone.now():
            return badge("expired", "muted")
        return badge("usable", "info")


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(_TokenAdmin):
    list_display = ("created_at", "client", "state_col", "expires_at", "consumed_at", "requested_ip")
    exclude = ("token_hash",)
    fields = ("client", "state_col", ("expires_at", "consumed_at", "invalidated_at"), "requested_ip", ("created_at", "updated_at"))


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(_TokenAdmin):
    list_display = ("created_at", "client", "email", "state_col", "expires_at", "consumed_at", "requested_ip")
    search_fields = ("client__email", "email")
    exclude = ("token_hash",)
    fields = ("client", "email", "state_col", ("expires_at", "consumed_at", "invalidated_at"), "requested_ip", ("created_at", "updated_at"))


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(ClientTeamInvite)
class ClientTeamInviteAdmin(ItrixModelAdmin):
    list_display = ("email", "client", "status_col", "created_at")
    list_filter = ("status",)
    search_fields = ("email", "client__email", "client__organization")
    raw_id_fields = ("client",)
    date_hierarchy = "created_at"

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)


@admin.register(ConsumedInvite)
class ConsumedInviteAdmin(AppendOnlyAdmin):
    list_display = ("created_at", "nonce_col", "lead_id")
    search_fields = ("nonce", "lead_id")
    date_hierarchy = "created_at"

    @admin.display(description="Nonce", ordering="nonce")
    def nonce_col(self, obj):
        return truncate(obj.nonce, 24)
