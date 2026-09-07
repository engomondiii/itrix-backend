"""Team-plane API for the existing ASTOP License-Out entitlement lifecycle."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import ASTOPEngagement, Lead
from apps.leads.serializers_entitlement import ASTOPEntitlementLifecycleSerializer
from apps.leads.services.entitlement_lifecycle import (
    entitlement_lifecycle_state,
    update_astop_entitlement,
)


def _payload(lead: Lead, record: ASTOPEngagement) -> dict:
    return {
        "leadId": str(lead.id),
        "astopStage": record.stage,
        "loExecutedAt": record.lo_executed_at,
        "entitlementStatus": record.entitlement_status,
        "entitlementLifecycleState": entitlement_lifecycle_state(record),
        "entitlementExpiresAt": record.entitlement_expires_at,
        "revocationStatus": record.revocation_status,
        "authorizedInstallAt": record.authorized_install_at,
        "reproducibleValueAt": record.reproducible_value_at,
        "ttfvSeconds": record.ttfv_seconds,
    }


class ASTOPEntitlementLifecycleView(APIView):
    """Read or mutate ASTOP entitlement state; never mounted on the client plane."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_permissions(self):
        permissions = [IsAuthenticated(), IsDashboardUser()]
        if self.request.method not in SAFE_METHODS:
            permissions.append(IsNotViewer())
        return permissions

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        record = ASTOPEngagement.objects.filter(lead=lead).first()
        if record is None:
            return Response(
                {"leadId": str(lead.id), "entitlement": None},
                status=status.HTTP_200_OK,
            )
        return Response(_payload(lead, record))

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        serializer = ASTOPEntitlementLifecycleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = update_astop_entitlement(
                lead,
                action=data["action"],
                expires_at=data.get("expires_at"),
                reason=data.get("reason", ""),
                by=request.user,
            )
        except ValueError as exc:
            raise ValidationError({"gate": str(exc)}) from exc
        return Response({**_payload(lead, result.record), "changed": result.changed})
