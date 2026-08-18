"""
Persona admin — read-mostly. The registry is seeded, not hand-edited, but the
33-field record is exactly the thing an operator wants to *read* in one
place, so the form is grouped into the sections the persona brief uses, with
the pitch room's slides shown inline.

INTERNAL-ONLY: persona fields never reach the anonymous plane.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin import (
    ItrixModelAdmin,
    ReadOnlyStackedInline,
    badge,
    count_link,
    link_to,
    pretty_json,
)
from apps.leads.models import Lead
from apps.personas.models import Persona, PitchRoom


class PitchRoomInline(ReadOnlyStackedInline):
    model = PitchRoom
    fields = (("pitch_room_id", "review_status", "slide_count_col"), "title", "slides_pretty")
    readonly_fields = ("slide_count_col", "slides_pretty")
    verbose_name_plural = "Pitch room"

    @admin.display(description="Slides")
    def slide_count_col(self, obj):
        return obj.slide_count

    @admin.display(description="Slides (rendered)")
    def slides_pretty(self, obj):
        return pretty_json(obj.slides)


@admin.register(Persona)
class PersonaAdmin(ItrixModelAdmin):
    list_display = (
        "persona_id",
        "company",
        "department",
        "primary_persona",
        "family_col",
        "priority",
        "validation_col",
        "disclosure_col",
        "leads_col",
        "pitch_room_col",
    )
    list_filter = ("functional_family", "validation_status", "disclosure_ceiling", "priority", "company")
    search_fields = ("persona_id", "company", "department", "primary_persona", "pitch_archetype", "buying_role")
    ordering = ("persona_id",)
    readonly_fields = ("id", "created_at", "updated_at", "supporting_kpis_pretty")
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    ("persona_id", "priority"),
                    ("company", "department"),
                    ("primary_persona", "functional_family"),
                    ("pitch_archetype", "buying_role", "decision_lens"),
                    ("validation_status", "disclosure_ceiling"),
                    "department_confidence",
                )
            },
        ),
        (
            "Mandate & pressure",
            {"fields": ("department_mandate", "trigger_event", ("primary_kpi",), "supporting_kpis", "supporting_kpis_pretty", "workload_environment")},
        ),
        (
            "Hypothesis",
            {"fields": ("boundary_waste_hypothesis", "desired_gain")},
        ),
        (
            "People",
            {"fields": (("likely_champion", "likely_blocker"), "likely_objection", "response_angle")},
        ),
        (
            "Commercial route",
            {
                "fields": (
                    "eligibility_gate",
                    "proof_contract",
                    "expansion_rule",
                    ("first_value_artifact", "personalized_cta"),
                    ("commercial_route", "product_route"),
                )
            },
        ),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )
    inlines = [PitchRoomInline]

    @admin.display(description="Family", ordering="functional_family")
    def family_col(self, obj):
        return badge(obj.functional_family, "info")

    @admin.display(description="Validation", ordering="validation_status")
    def validation_col(self, obj):
        return badge(obj.validation_status)

    @admin.display(description="Ceiling", ordering="disclosure_ceiling")
    def disclosure_col(self, obj):
        return badge(obj.disclosure_ceiling)

    @admin.display(description="Leads")
    def leads_col(self, obj):
        return count_link(Lead, obj.leads.count(), persona__id__exact=obj.pk)

    @admin.display(description="Pitch room")
    def pitch_room_col(self, obj):
        room = getattr(obj, "pitch_room", None)
        return link_to(room, room.pitch_room_id) if room else "—"

    @admin.display(description="Supporting KPIs (rendered)")
    def supporting_kpis_pretty(self, obj):
        return pretty_json(obj.supporting_kpis)


@admin.register(PitchRoom)
class PitchRoomAdmin(ItrixModelAdmin):
    list_display = ("pitch_room_id", "persona", "title", "slide_count_col", "review_status", "updated_at")
    list_filter = ("review_status", "persona__functional_family")
    search_fields = ("pitch_room_id", "title", "persona__persona_id", "persona__company")
    autocomplete_fields = ("persona",)
    ordering = ("pitch_room_id",)
    readonly_fields = ("id", "created_at", "updated_at", "slides_pretty")
    fieldsets = (
        (None, {"fields": (("pitch_room_id", "persona"), "title", "review_status")}),
        ("Slides", {"fields": ("slides", "slides_pretty")}),
        ("Timestamps", {"fields": (("created_at", "updated_at"), "id")}),
    )

    @admin.display(description="Slides")
    def slide_count_col(self, obj):
        return obj.slide_count

    @admin.display(description="Slides (rendered)")
    def slides_pretty(self, obj):
        return pretty_json(obj.slides)
