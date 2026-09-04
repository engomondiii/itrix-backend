"""Admin for generated result pages (read-only — they are generated, not authored)."""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from apps.core.admin import (
    ReadOnlyAdmin,
    badge,
    bool_badge,
    pretty_json,
    short_id,
    tier_badge,
    truncate,
)
from apps.result_page.models import (
    ClientPageAccessGrant,
    ClientPageAccessSession,
    ResultPage,
)


@admin.register(ResultPage)
class ResultPageAdmin(ReadOnlyAdmin):
    list_display = ("generated_at", "lead", "tier_col", "product_route", "license_pathway", "ai_col", "next_step_col")
    list_filter = ("tier", "product_route", "license_pathway", "used_ai")
    search_fields = ("lead__company", "lead__email", "problem_mirror", "alpha_fit_summary")
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    list_select_related = ("lead",)
    readonly_fields = ("score_breakdown_pretty", "primary_technologies_pretty", "diagnosis_pretty", "kpi_preview_pretty", "proof_preview_pretty")
    fieldsets = (
        ("Page", {"fields": (("lead", "generated_at"), ("tier", "product_route", "license_pathway"), "used_ai", "id")}),
        ("Narrative", {"fields": ("problem_mirror", "alpha_fit_summary", "recommended_next_step")}),
        ("Structured", {"fields": ("diagnosis_pretty", "primary_technologies_pretty", "kpi_preview_pretty", "proof_preview_pretty", "score_breakdown_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(description="Tier", ordering="tier")
    def tier_col(self, obj):
        return tier_badge(obj.tier)

    @admin.display(description="AI", ordering="used_ai")
    def ai_col(self, obj):
        return bool_badge(obj.used_ai, "AI", "template")

    @admin.display(description="Next step")
    def next_step_col(self, obj):
        return truncate(obj.recommended_next_step, 70)

    @admin.display(description="Score breakdown")
    def score_breakdown_pretty(self, obj):
        return pretty_json(obj.score_breakdown)

    @admin.display(description="Primary technologies")
    def primary_technologies_pretty(self, obj):
        return pretty_json(obj.primary_technologies)

    @admin.display(description="Diagnosis")
    def diagnosis_pretty(self, obj):
        return pretty_json(obj.diagnosis)

    @admin.display(description="KPI preview")
    def kpi_preview_pretty(self, obj):
        return pretty_json(obj.kpi_preview)

    @admin.display(description="Proof preview")
    def proof_preview_pretty(self, obj):
        return pretty_json(obj.proof_preview)


# ── My Review access credentials ─────────────────────────────────────────────
# Both tables store hashes, never the credential itself: the exchange code lives
# only in the emailed URL and the session token only in an httpOnly cookie. They
# are registered so support can answer "did that link work, and is it spent?"
# without anyone being able to read, mint or edit a credential from here — which
# is why they are strictly inspect-only.


class AccessLifecycleMixin:
    @admin.display(description="State")
    def state_col(self, obj):
        if obj.revoked_at:
            return badge("revoked", "danger")
        if obj.expires_at and obj.expires_at <= timezone.now():
            return badge("expired", "danger")
        if getattr(obj, "consumed_at", None):
            return badge("consumed", "muted")
        return badge("active", "success")


@admin.register(ClientPageAccessGrant)
class ClientPageAccessGrantAdmin(AccessLifecycleMixin, ReadOnlyAdmin):
    list_display = ("created_at", "lead", "state_col", "bound_col", "expires_at", "consumed_at", "fingerprint_col")
    list_filter = ("expires_at", "consumed_at", "revoked_at")
    search_fields = ("lead__company", "lead__email", "client_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("lead",)
    fieldsets = (
        ("Grant", {"fields": (("lead", "client_id"), "fingerprint_col")}),
        ("Lifecycle", {"fields": (("expires_at", "consumed_at", "revoked_at"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Bound to")
    def bound_col(self, obj):
        if obj.client_id:
            return badge("client", "info")
        return badge("browser", "muted") if obj.visitor_session_hash else badge("unbound", "warning")

    @admin.display(description="Code")
    def fingerprint_col(self, obj):
        # A prefix of the hash — enough to correlate with a support report, and
        # useless as a credential.
        return short_id(obj.code_hash)


@admin.register(ClientPageAccessSession)
class ClientPageAccessSessionAdmin(AccessLifecycleMixin, ReadOnlyAdmin):
    list_display = ("created_at", "grant", "state_col", "last_seen_at", "expires_at", "fingerprint_col")
    list_filter = ("expires_at", "revoked_at")
    search_fields = ("grant__lead__company", "grant__lead__email")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("grant", "grant__lead")
    fieldsets = (
        ("Session", {"fields": ("grant", "fingerprint_col")}),
        ("Lifecycle", {"fields": (("expires_at", "last_seen_at", "revoked_at"),)}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Token")
    def fingerprint_col(self, obj):
        return short_id(obj.token_hash)
