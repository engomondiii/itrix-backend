"""
Journey views.

    GET  journey/{token}/               PUBLIC — resolve a capability token to the
                                        current journey state + authorized surface + reveals
    GET  journey/leads/{id}/            TEAM   — a lead's journey + transition history
    POST journey/leads/{id}/advance/    TEAM   — guarded manual advance (audit-logged)

The public endpoint accepts any of the capability-token types; it verifies the
signature + expiry, loads the subject lead, and returns only what the journey permits.
It never mutates state.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsJourneyController
from apps.core.permissions import IsDashboardUser
from apps.journey.models import STATE_REVEAL, JourneyState
from apps.journey.serializers import (
    AdvanceRequestSerializer,
    JourneyLeadSerializer,
    JourneyStateSerializer,
)
from apps.journey.services import advance as advance_svc
from apps.journey.services import capability_token as ct
from apps.journey.services.gate import account_invite_allowed
from apps.journey.services.reveal import reveal_for_state

logger = logging.getLogger("itrix")


def _load_lead(sub: str):
    from apps.leads.models import Lead

    return Lead.objects.filter(id=sub).first()


def _journey_payload(lead) -> dict:
    state = lead.journey_state or JourneyState.ARRIVED
    reveal = reveal_for_state(lead, state)
    reveals = [reveal] if reveal else []
    return {
        "state": state,
        "authorizedSurface": STATE_REVEAL.get(state) or None,
        "valueDelivered": getattr(lead, "value_delivered_at", None) is not None,
        "accountInviteAvailable": account_invite_allowed(lead),
        "reveals": reveals,
    }


class JourneyByTokenView(APIView):
    """GET journey/{token}/ — PUBLIC. Resolve a capability token to journey state."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, token: str):
        try:
            payload = ct.verify(token)
        except ct.CapabilityTokenError as exc:
            return Response(
                {"detail": f"Invalid token: {exc}"}, status=status.HTTP_404_NOT_FOUND
            )

        lead = _load_lead(payload.sub)
        if lead is None:
            return Response({"detail": "Unknown subject."}, status=status.HTTP_404_NOT_FOUND)

        data = JourneyStateSerializer(_journey_payload(lead)).data
        return Response(data, status=status.HTTP_200_OK)


class JourneyLeadView(APIView):
    """GET journey/leads/{id}/ — TEAM. A lead's journey + transition history."""

    permission_classes = [IsDashboardUser]

    def get(self, request, lead_id):
        from apps.leads.models import Lead

        lead = get_object_or_404(Lead, id=lead_id)
        payload = {
            "leadId": str(lead.id),
            "state": lead.journey_state or JourneyState.ARRIVED,
            "valueDelivered": getattr(lead, "value_delivered_at", None) is not None,
            "accountInviteAvailable": account_invite_allowed(lead),
            "transitions": lead.journey_transitions.all(),
        }
        return Response(JourneyLeadSerializer(payload).data, status=status.HTTP_200_OK)


class JourneyOverviewView(APIView):
    """
    GET journey/overview/ — TEAM. How many leads sit in each journey state.

    Feeds the Surface 2 overview widget. Counts in one query; states with no leads
    are returned as 0 so the client can render a stable set of bars.
    """

    permission_classes = [IsDashboardUser]

    def get(self, request):
        from django.db.models import Count

        from apps.leads.models import Lead

        counts = dict(
            Lead.objects.values_list("journey_state")
            .annotate(n=Count("id"))
            .values_list("journey_state", "n")
        )
        distribution = {state.value: counts.get(state.value, 0) for state in JourneyState}
        return Response({"distribution": distribution, "total": sum(distribution.values())})


class JourneyAdvanceView(APIView):
    """POST journey/leads/{id}/advance/ — TEAM. Guarded manual advance (audited)."""

    permission_classes = [IsJourneyController]

    def post(self, request, lead_id):
        from apps.leads.models import Lead

        lead = get_object_or_404(Lead, id=lead_id)
        ser = AdvanceRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            result = advance_svc.advance(
                lead,
                ser.validated_data["event"],
                actor=request.user,
                meta=ser.validated_data.get("meta", {}),
            )
        except advance_svc.InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "leadId": str(lead.id),
                "fromState": result.from_state,
                "toState": result.to_state,
                "event": result.event,
                "changed": result.changed,
                "reveal": result.reveal,
            },
            status=status.HTTP_200_OK,
        )
