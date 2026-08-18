"""
Admin for leads, notes, meetings and activity.

The Lead is the hub of the CRM — seventeen other models hang off it — so its
change page is built as a dossier: identity and qualification on the first
tabs, then every satellite (notes, meetings, timeline, follow-ups, NDA,
evaluations, PoCs, journey transitions, emails, agent runs, conversations)
as an inline tab so an operator can understand the whole relationship from
one screen without hopping between changelists.
"""

from __future__ import annotations

from django.contrib import admin
from django.utils.safestring import mark_safe

from apps.agents.models import AgentRun
from apps.conversations.models import Conversation, Thread
from apps.core.admin import (
    AppendOnlyAdmin,
    EditableStackedInline,
    EditableTabularInline,
    ItrixModelAdmin,
    ReadOnlyTabularInline,
    badge,
    bool_badge,
    count_link,
    link_to,
    pretty_json,
    short_id,
    tier_badge,
    truncate,
)
from apps.emails.models import EmailLog
from apps.evaluations.models import Evaluation
from apps.follow_up.models import FollowUpTask
from apps.journey.models import JourneyTransition
from apps.leads.models import Lead, LeadActivity, LeadMeeting, LeadNote
from apps.nda.models import NDARecord
from apps.pocs.models import PoC

# ─────────────────────────────────────────────────────────────────────────────
# Inlines — the lead's satellites
# ─────────────────────────────────────────────────────────────────────────────


class LeadNoteInline(EditableTabularInline):
    model = LeadNote
    fields = ("body", "author", "author_name", "created_at")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("author",)
    verbose_name_plural = "Notes"


class LeadMeetingInline(EditableTabularInline):
    model = LeadMeeting
    fields = ("scheduled_at", "duration_mins", "attendee", "location", "booked_by", "notes")
    autocomplete_fields = ("booked_by",)
    verbose_name_plural = "Meetings"


class LeadActivityInline(ReadOnlyTabularInline):
    model = LeadActivity
    fields = ("created_at", "type", "label", "by_name")
    ordering = ("-created_at",)
    verbose_name_plural = "Timeline"


class FollowUpTaskInline(EditableTabularInline):
    model = FollowUpTask
    fields = ("due_at", "status", "owner", "tier", "snoozed_until", "note")
    autocomplete_fields = ("owner",)
    verbose_name_plural = "Follow-up tasks"


class NDARecordInline(EditableStackedInline):
    model = NDARecord
    fields = (
        ("status", "doc_type"),
        ("signer_name", "signer_email"),
        ("requested_at", "sent_at", "signed_at"),
        "decline_reason",
    )
    readonly_fields = ("requested_at",)
    max_num = 1
    verbose_name_plural = "NDA"


class EvaluationInline(EditableTabularInline):
    model = Evaluation
    fields = ("pkg", "status", "fee", "timeline", "created_at")
    readonly_fields = ("created_at",)
    verbose_name_plural = "Evaluations"


class PoCInline(EditableTabularInline):
    model = PoC
    fields = ("status", "duration_weeks", "start_date", "created_at")
    readonly_fields = ("created_at",)
    verbose_name_plural = "PoCs"


class JourneyTransitionInline(ReadOnlyTabularInline):
    model = JourneyTransition
    fields = ("created_at", "from_state", "to_state", "event", "reveal", "actor")
    ordering = ("-created_at",)
    verbose_name_plural = "Journey transitions"


class EmailLogInline(ReadOnlyTabularInline):
    model = EmailLog
    fields = ("created_at", "kind", "to_email", "subject", "status")
    ordering = ("-created_at",)
    verbose_name_plural = "Emails"


class AgentRunInline(ReadOnlyTabularInline):
    model = AgentRun
    fields = ("created_at", "agent_key", "status", "governance_status", "claim_level", "used_ai", "duration_ms")
    ordering = ("-created_at",)
    verbose_name_plural = "Agent runs"


class ConversationInline(ReadOnlyTabularInline):
    model = Conversation
    fk_name = "lead"
    fields = ("context", "title", "client", "is_active", "last_message_at")
    verbose_name_plural = "Conversations"


class ThreadInline(ReadOnlyTabularInline):
    model = Thread
    fk_name = "lead"
    fields = ("context", "title", "owner_kind", "current_state", "questions_asked", "last_activity_at")
    verbose_name_plural = "Threads"


# ─────────────────────────────────────────────────────────────────────────────
# Lead
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Lead)
class LeadAdmin(ItrixModelAdmin):
    list_display = (
        "company_col",
        "email",
        "tier_col",
        "score",
        "status_col",
        "journey_state",
        "product_route",
        "commercial_path",
        "owner",
        "escalated_col",
        "submitted_at",
    )
    list_display_links = ("company_col", "email")
    list_filter = (
        "tier",
        "status",
        "journey_state",
        "product_route",
        "commercial_path",
        "special_rights",
        "lead_source",
        "escalated",
        "human_handoff_trigger",
        ("owner", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("company", "visitor_name", "email", "industry", "role", "client_id", "id")
    autocomplete_fields = ("owner", "persona")
    raw_id_fields = ("review_session", "first_thread")
    date_hierarchy = "submitted_at"
    ordering = ("-submitted_at",)
    list_select_related = ("owner",)
    readonly_fields = (
        "id",
        "review_session",
        "client_id",
        "lead_source",
        "value_delivered_at",
        "gate_decision",
        "gate_decision_reason",
        "journey_number",
        "state_key",
        "first_thread",
        "attachment_count",
        "submitted_at",
        "created_at",
        "updated_at",
        "score_breakdown_pretty",
        "qualification_pretty",
        "current_stack_pretty",
        "client_account_link",
        "result_page_link",
        "escalated_at",
        "first_response_at",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    ("company", "visitor_name"),
                    ("email", "role"),
                    ("industry", "lead_source"),
                    ("client_id", "id"),
                    ("client_account_link", "result_page_link"),
                )
            },
        ),
        (
            "Qualification",
            {
                "fields": (
                    ("tier", "score"),
                    ("product_route", "commercial_path"),
                    ("special_rights",),
                    ("compute_bottleneck",),
                    ("primary_pain", "workload_type"),
                    ("commercial_intent", "timeline"),
                    "current_stack_pretty",
                    "score_breakdown_pretty",
                    "qualification_pretty",
                    "recommended_next_step",
                    "human_handoff_trigger",
                )
            },
        ),
        (
            "Pipeline & ownership",
            {
                "fields": (
                    ("status", "owner"),
                    ("sla_response_due_at", "first_response_at"),
                    ("escalated", "escalated_at"),
                    ("cta_clicked", "documents_viewed"),
                    "persona",
                )
            },
        ),
        (
            "Journey",
            {
                "fields": (
                    ("journey_state", "journey_number", "state_key"),
                    ("gate_decision", "gate_decision_reason"),
                    ("value_delivered_at",),
                    ("review_session", "first_thread", "attachment_count"),
                )
            },
        ),
        ("Timestamps", {"fields": (("submitted_at", "created_at", "updated_at"),)}),
    )
    inlines = [
        LeadNoteInline,
        LeadMeetingInline,
        LeadActivityInline,
        FollowUpTaskInline,
        NDARecordInline,
        EvaluationInline,
        PoCInline,
        JourneyTransitionInline,
        ConversationInline,
        ThreadInline,
        EmailLogInline,
        AgentRunInline,
    ]

    # ── columns ────────────────────────────────────────────────────────────
    @admin.display(description="Company / name", ordering="company")
    def company_col(self, obj):
        return obj.company or obj.visitor_name or short_id(obj.id)

    @admin.display(description="Tier", ordering="tier")
    def tier_col(self, obj):
        return tier_badge(obj.tier)

    @admin.display(description="Status", ordering="status")
    def status_col(self, obj):
        return badge(obj.status)

    @admin.display(description="Esc.", ordering="escalated", boolean=True)
    def escalated_col(self, obj):
        return obj.escalated

    # ── read-only detail renderers ─────────────────────────────────────────
    @admin.display(description="Score breakdown")
    def score_breakdown_pretty(self, obj):
        return pretty_json(obj.score_breakdown)

    @admin.display(description="Qualification")
    def qualification_pretty(self, obj):
        return pretty_json(obj.qualification)

    @admin.display(description="Current stack")
    def current_stack_pretty(self, obj):
        return pretty_json(obj.current_stack)

    @admin.display(description="Client account")
    def client_account_link(self, obj):
        client = getattr(obj, "client_account", None)
        return link_to(client) if client else mark_safe('<span class="text-muted">no account yet</span>')

    @admin.display(description="Result page")
    def result_page_link(self, obj):
        page = getattr(obj, "result_page", None)
        return link_to(page, f"Result page (T{page.tier})") if page else mark_safe('<span class="text-muted">not generated</span>')


# ─────────────────────────────────────────────────────────────────────────────
# Satellites — standalone changelists for search across all leads
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(LeadNote)
class LeadNoteAdmin(ItrixModelAdmin):
    list_display = ("created_at", "lead", "author_name", "body_col")
    list_filter = (("author", admin.RelatedOnlyFieldListFilter),)
    search_fields = ("body", "author_name", "lead__company", "lead__email")
    autocomplete_fields = ("lead", "author")
    date_hierarchy = "created_at"

    @admin.display(description="Note")
    def body_col(self, obj):
        return truncate(obj.body, 120)


@admin.register(LeadMeeting)
class LeadMeetingAdmin(ItrixModelAdmin):
    list_display = ("scheduled_at", "lead", "duration_mins", "attendee", "location", "booked_by_name")
    list_filter = (("booked_by", admin.RelatedOnlyFieldListFilter),)
    search_fields = ("attendee", "location", "notes", "lead__company", "lead__email")
    autocomplete_fields = ("lead", "booked_by")
    date_hierarchy = "scheduled_at"
    ordering = ("-scheduled_at",)


@admin.register(LeadActivity)
class LeadActivityAdmin(AppendOnlyAdmin):
    list_display = ("created_at", "lead", "type_col", "label", "by_name")
    list_filter = ("type", ("by", admin.RelatedOnlyFieldListFilter))
    search_fields = ("label", "by_name", "lead__company", "lead__email")
    date_hierarchy = "created_at"
    readonly_fields = ("meta_pretty",)
    fields = ("lead", "type", "label", ("by", "by_name"), "meta_pretty", ("created_at", "updated_at"))

    @admin.display(description="Type", ordering="type")
    def type_col(self, obj):
        return badge(obj.type, "info")

    @admin.display(description="Meta")
    def meta_pretty(self, obj):
        return pretty_json(obj.meta)
