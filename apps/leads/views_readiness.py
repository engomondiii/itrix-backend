"""Team-plane ASTOP production-readiness API."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminRole, IsDashboardUser
from apps.leads.models import ASTOPEngagement, Lead
from apps.leads.serializers_readiness import ASTOPReadinessSerializer
from apps.leads.services.readiness import current_readiness, overall_readiness_state, set_astop_readiness


class ASTOPReadinessView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_permissions(self):
        permissions = [IsAuthenticated(), IsDashboardUser()]
        if self.request.method not in SAFE_METHODS:
            permissions.append(IsAdminRole())
        return permissions

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        record = ASTOPEngagement.objects.filter(lead=lead).first()
        if record is None:
            return Response({"leadId": str(lead.id), "overall": "NOT_PROVIDED", "readiness": {}})
        return Response(
            {
                "leadId": str(lead.id),
                "overall": overall_readiness_state(record),
                "readiness": current_readiness(record),
            }
        )

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        serializer = ASTOPReadinessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = set_astop_readiness(
                lead,
                updates=serializer.validated_data["readiness"],
                by=request.user,
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"gate": str(exc)}) from exc
        return Response(
            {
                "leadId": str(lead.id),
                "overall": overall_readiness_state(result.record),
                "readiness": result.readiness,
                "changed": result.changed,
            }
        )
