"""
Governance views (TEAM plane).

    GET/POST governance/claim-cards/        list + create claim cards
    GET/PATCH governance/claim-cards/{id}/  retrieve + update a claim card
    GET       governance/audit/             the approval-request audit trail

Claim-card writes require the governance-admin role gate (ADMIN/ASSESSMENT); reads are
open to any dashboard user. The approval-QUEUE actions (queue list, approve/edit/reject)
live in apps.agents.views alongside the console + cockpit so the S2 oversight surface is
one coherent module.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.permissions import IsGovernanceAdmin
from apps.core.permissions import IsDashboardUser
from apps.governance.models import ApprovalRequest, ClaimCard
from apps.governance.serializers import (
    ApprovalRequestSerializer,
    ClaimCardSerializer,
)


class ClaimCardListCreateView(APIView):
    """GET (list) + POST (create) governance/claim-cards/."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsGovernanceAdmin()]
        return [IsAuthenticated(), IsDashboardUser()]

    def get(self, request):
        cards = ClaimCard.objects.all()
        level = request.query_params.get("level")
        if level:
            cards = cards.filter(claim_level=level)
        return Response(ClaimCardSerializer(cards, many=True).data)

    def post(self, request):
        ser = ClaimCardSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        card = ser.save(owner=request.user)
        return Response(ClaimCardSerializer(card).data, status=status.HTTP_201_CREATED)


class ClaimCardDetailView(APIView):
    """GET + PATCH governance/claim-cards/{id}/."""

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAuthenticated(), IsGovernanceAdmin()]
        return [IsAuthenticated(), IsDashboardUser()]

    def get(self, request, card_id):
        card = get_object_or_404(ClaimCard, id=card_id)
        return Response(ClaimCardSerializer(card).data)

    def patch(self, request, card_id):
        card = get_object_or_404(ClaimCard, id=card_id)
        ser = ClaimCardSerializer(card, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ClaimCardSerializer(card).data)


class GovernanceAuditView(APIView):
    """GET governance/audit/ — the approval-request audit trail (read-only)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        qs = ApprovalRequest.objects.all().order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(ApprovalRequestSerializer(qs[:500], many=True).data)
