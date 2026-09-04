"""
Shared admin toolkit for the itriX backend.

Every app's ``admin.py`` builds on the pieces here so the admin reads as ONE
surface: the same column conventions, the same badge colours for the same
statuses, the same treatment of UUIDs / JSON blobs / timestamps, and the same
three postures towards editing —

* :class:`ItrixModelAdmin`  — the default: editable, id + timestamps read-only.
* :class:`AppendOnlyAdmin`  — the audit-trail posture: rows can be created by
  the system and inspected by staff, never edited from here (superusers may
  delete).
* :class:`ReadOnlyAdmin`    — telemetry / evidence: inspect only.

Nothing in this module knows about any particular app; the helpers are
deliberately generic so a new model gets a good admin in a dozen lines.
"""

from __future__ import annotations

import json
from typing import Any, Iterable
from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers
# ─────────────────────────────────────────────────────────────────────────────

#: Bootstrap contextual colours keyed by the *meaning* of a value, so a status
#: that means "good" is always green whatever the model calls it.
TONE_CLASSES = {
    "success": "badge bg-success",
    "info": "badge bg-info text-dark",
    "warning": "badge bg-warning text-dark",
    "danger": "badge bg-danger",
    "muted": "badge bg-secondary",
    "primary": "badge bg-primary",
    "dark": "badge bg-dark",
}

#: One shared vocabulary → tone map. Add here, not per-app, so "approved" is
#: the same green in governance, conversations, journey and agents.
STATUS_TONES: dict[str, str] = {
    # good / done
    "ok": "success", "approved": "success", "auto_approved": "success", "signed": "success",
    "achieved": "success", "completed": "success", "resolved": "success", "healthy": "success",
    "clean": "success", "ready": "success", "sent": "success", "won": "success", "settled": "success",
    "validated": "success", "COMPLETE": "success", "QUALIFIED": "success", "covered": "success",
    "Licensed": "success", "active": "success", "delivered": "success", "published": "success",
    "on_plan": "success", "shipped": "success", "CUSTOMER_SUCCESS": "success", "public": "success",
    # in progress / attention
    "pending": "warning", "awaiting_second": "warning", "in_progress": "info", "streaming": "info",
    "scanning": "info", "extracting": "info", "PROCESSING": "info", "PROMPTED": "info",
    "STARTED": "muted", "planning": "info", "proposed": "info", "waiting_on_customer": "warning",
    "at_risk": "warning", "degraded": "warning", "partial": "warning", "snoozed": "muted",
    "fallback": "warning", "hypothesis": "warning", "under_review": "warning", "suspicious": "warning",
    "required": "warning", "open": "info", "staged": "muted", "scanned": "info", "unknown": "muted",
    "stubbed": "muted", "PENDING": "muted", "New": "primary", "Contacted": "info", "Qualifying": "info",
    "Meeting Booked": "info", "NDA": "info", "Evaluation": "info", "PoC": "info", "Negotiation": "info",
    "Nurture": "muted", "edited": "info", "awaiting_decision": "warning", "halted": "warning",
    "invited": "info", "controlled_public": "info", "authorized": "warning",
    "nda_only": "warning", "customer_contract": "warning",
    "envelope_downgrade": "warning", "settle_replacement": "info", "normal": "info", "low": "muted",
    "high": "warning",
    # bad / terminal
    "error": "danger", "failed": "danger", "FAILED": "danger", "blocked": "danger", "rejected": "danger",
    "declined": "danger", "expired": "danger", "off_plan": "danger", "down": "danger", "malicious": "danger",
    "quarantined": "danger", "purged": "dark", "lost": "danger", "Lost": "danger", "Closed": "muted",
    "cancelled": "muted", "stalled": "warning", "dismissed": "muted", "revoked": "danger",
    "critical": "danger", "prohibited": "danger", "internal_only": "dark", "halt": "danger",
    "DORMANT": "muted",
}


def dash() -> SafeString:
    return mark_safe('<span class="text-muted">—</span>')


def badge(value: Any, tone: str | None = None, label: str | None = None) -> SafeString:
    """Render ``value`` as a Bootstrap badge, colour chosen from STATUS_TONES."""
    if value in (None, ""):
        return dash()
    tone = tone or STATUS_TONES.get(str(value), "muted")
    return format_html('<span class="{}">{}</span>', TONE_CLASSES[tone], label if label is not None else value)


def bool_badge(value: bool | None, yes: str = "yes", no: str = "no") -> SafeString:
    if value is None:
        return dash()
    return badge(yes if value else no, "success" if value else "muted")


def tier_badge(tier: int | None) -> SafeString:
    """Lead tiers: 1 is hottest. Colour accordingly."""
    if tier is None:
        return dash()
    tone = {1: "danger", 2: "warning", 3: "info", 4: "muted"}.get(int(tier), "muted")
    return badge(f"T{tier}", tone)


def claim_level_badge(level: int | None) -> SafeString:
    """Governance claim levels 1–5: higher = more restricted."""
    if level is None:
        return dash()
    tone = {1: "success", 2: "success", 3: "info", 4: "warning", 5: "danger"}.get(int(level), "muted")
    return badge(f"L{level}", tone)


def short_id(value: Any, chars: int = 8) -> str:
    """The first ``chars`` of a UUID — enough to eyeball, short enough for a column."""
    return str(value)[:chars] if value else "—"


def pretty_json(value: Any, max_chars: int = 20_000) -> SafeString:
    """Readable, monospace JSON for a read-only field."""
    if value in (None, "", {}, []):
        return mark_safe('<span class="text-muted">— empty —</span>')
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n… truncated ({len(text) - max_chars} more chars)"
    return format_html('<pre class="itrix-json">{}</pre>', text)


def admin_url_for(obj: models.Model | None) -> str | None:
    if obj is None:
        return None
    meta = obj._meta
    try:
        return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])
    except NoReverseMatch:
        return None


def link_to(obj: models.Model | None, label: str | None = None) -> SafeString:
    """A link to ``obj``'s change page, or an em-dash."""
    if obj is None:
        return dash()
    url = admin_url_for(obj)
    text = label if label is not None else str(obj)
    if not url:
        return format_html("{}", text)
    return format_html('<a href="{}">{}</a>', url, text)


def changelist_url(model: type[models.Model], **filters: Any) -> str | None:
    meta = model._meta
    try:
        base = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
    except NoReverseMatch:
        return None
    return f"{base}?{urlencode(filters)}" if filters else base


def count_link(model: type[models.Model], count: int, **filters: Any) -> SafeString:
    """A count that links to the filtered changelist. Used for reverse-relation columns."""
    url = changelist_url(model, **filters)
    if not url or not count:
        return format_html("{}", count)
    return format_html('<a href="{}">{}</a>', url, count)


def truncate(text: str | None, length: int = 80) -> str:
    if not text:
        return "—"
    text = " ".join(str(text).split())
    return text if len(text) <= length else text[: length - 1] + "…"


def bullet_list(items: Iterable[Any]) -> SafeString:
    items = list(items or [])
    if not items:
        return dash()
    return format_html('<ul class="itrix-list">{}</ul>', format_html_join("", "<li>{}</li>", ((i,) for i in items)))


# ─────────────────────────────────────────────────────────────────────────────
# ModelAdmin bases
# ─────────────────────────────────────────────────────────────────────────────

BASE_READONLY = ("id", "created_at", "updated_at")


class ItrixModelAdmin(admin.ModelAdmin):
    """
    Default posture for every itriX model.

    * ``id`` / ``created_at`` / ``updated_at`` are always read-only.
    * ``list_per_page`` is modest — the changelists carry many columns.
    * ``save_on_top`` because several forms are long (Lead, Persona, Client).
    * ``list_select_related`` is derived from the FK columns in ``list_display``
      unless set explicitly, so a changelist never fires a query per row.
    """

    list_per_page = 50
    save_on_top = True
    empty_value_display = "—"

    def get_readonly_fields(self, request, obj=None):
        ro = tuple(super().get_readonly_fields(request, obj))
        model_fields = {f.name for f in self.model._meta.fields}
        extra = tuple(f for f in BASE_READONLY if f in model_fields and f not in ro)
        return ro + extra

    def get_list_select_related(self, request):
        if self.list_select_related is not False:
            return self.list_select_related
        related = []
        for name in self.list_display:
            try:
                field = self.model._meta.get_field(name)
            except Exception:  # noqa: BLE001 - a callable / method column
                continue
            if getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
                related.append(name)
        return related or False


class ReadOnlyAdmin(ItrixModelAdmin):
    """Inspect-only. Telemetry, evidence, and anything the system owns outright."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        # Everything, so the change form renders as a clean detail view. Declared
        # readonly_fields keep their order (they may include display methods).
        declared = tuple(super().get_readonly_fields(request, obj))
        model_fields = tuple(f.name for f in self.model._meta.fields)
        return tuple(dict.fromkeys(declared + model_fields))


class AppendOnlyAdmin(ReadOnlyAdmin):
    """Rows appear via the system; staff inspect, superusers may delete, nobody edits."""

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ─────────────────────────────────────────────────────────────────────────────
# Inline bases
# ─────────────────────────────────────────────────────────────────────────────


class _ReadOnlyInlineMixin:
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = getattr(self, "fields", None) or ()
        declared = tuple(super().get_readonly_fields(request, obj))  # type: ignore[misc]
        return tuple(dict.fromkeys(declared + tuple(fields)))


class ReadOnlyTabularInline(_ReadOnlyInlineMixin, admin.TabularInline):
    """A related-rows table that is purely for context — no add/edit/delete."""


class ReadOnlyStackedInline(_ReadOnlyInlineMixin, admin.StackedInline):
    """A read-only stacked inline (for one-to-one satellites with many fields)."""


class EditableTabularInline(admin.TabularInline):
    extra = 0
    show_change_link = True


class EditableStackedInline(admin.StackedInline):
    extra = 0
    show_change_link = True


# ─────────────────────────────────────────────────────────────────────────────
# Django's own admin log — surfaced so "who changed what in here" is answerable
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    """The admin's own audit trail. Read-only, superusers only."""

    list_display = ("action_time", "user", "content_type", "object_repr", "action_badge", "change_message")
    list_filter = ("action_flag", "content_type")
    search_fields = ("object_repr", "change_message", "user__email", "user__name")
    date_hierarchy = "action_time"
    readonly_fields = tuple(f.name for f in LogEntry._meta.fields)
    list_select_related = ("user", "content_type")
    list_per_page = 100

    @admin.display(description="Action", ordering="action_flag")
    def action_badge(self, obj):
        return {1: badge("added", "success"), 2: badge("changed", "info"), 3: badge("deleted", "danger")}.get(
            obj.action_flag, badge(obj.action_flag)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser
