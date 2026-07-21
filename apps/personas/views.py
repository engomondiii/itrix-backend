"""
Persona views — TEAM PLANE ONLY.

Read-only by design. ``IsDashboardUser`` gates both routes; there is no AllowAny path
into this module and there must never be one, because everything it serves is on the
§10.5 internal-only list.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser
from apps.personas.models import Persona
from apps.personas.serializers import PersonaDetailSerializer, PersonaSummarySerializer


class PersonaListView(APIView):
    """GET personas/ — TEAM. The registry browser."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        qs = Persona.objects.select_related("pitch_room").all()

        family = request.query_params.get("family")
        if family:
            qs = qs.filter(functional_family=family)
        company = request.query_params.get("company")
        if company:
            qs = qs.filter(company__iexact=company)
        status_filter = request.query_params.get("validation_status")
        if status_filter:
            qs = qs.filter(validation_status=status_filter)

        return Response(
            {
                "personas": PersonaSummarySerializer(qs, many=True).data,
                "total": qs.count(),
            }
        )


class PersonaDetailView(APIView):
    """GET personas/{persona_id}/ — TEAM. One persona and its room."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request, persona_id: str):
        persona = get_object_or_404(
            Persona.objects.select_related("pitch_room"), persona_id=persona_id
        )
        return Response(PersonaDetailSerializer(persona).data)
