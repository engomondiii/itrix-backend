"""
Persona routes (mounted at /api/v1/personas/) — TEAM PLANE ONLY.

    GET personas/            registry browser (read-only)
    GET personas/{id}/       one persona + its pitch room

There is deliberately no client-plane mount and no write endpoint. The registry is
SEEDED from the workbook (``manage.py seed_personas``), not hand-edited through an API —
so the workbook stays the source of truth and a research pass cannot be silently
overwritten by a UI edit.
"""

from __future__ import annotations

from django.urls import path

from apps.personas.views import PersonaDetailView, PersonaListView

app_name = "personas"

urlpatterns = [
    path("", PersonaListView.as_view(), name="persona-list"),
    path("<str:persona_id>/", PersonaDetailView.as_view(), name="persona-detail"),
]
