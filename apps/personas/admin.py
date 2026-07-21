"""Persona admin — read-mostly. The registry is seeded, not hand-edited."""

from __future__ import annotations

from django.contrib import admin

from apps.personas.models import Persona, PitchRoom


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = (
        "persona_id",
        "company",
        "department",
        "functional_family",
        "priority",
        "validation_status",
    )
    list_filter = ("functional_family", "validation_status", "priority", "company")
    search_fields = ("persona_id", "company", "department", "primary_persona")
    ordering = ("persona_id",)


@admin.register(PitchRoom)
class PitchRoomAdmin(admin.ModelAdmin):
    list_display = ("pitch_room_id", "persona", "title", "slide_count", "review_status")
    search_fields = ("pitch_room_id", "title")
    ordering = ("pitch_room_id",)
