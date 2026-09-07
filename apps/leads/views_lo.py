"""Admin-only team-plane API for governed ASTOP License-Out terms."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdminRole, IsDashboardUser
from apps.leads.models import ASTOPEngagement, Lead
from apps.leads.serializers_lo import GovernedLOTermsSerializer
from apps.leads.services.lo_terms import set_governed_lo_terms


class GovernedLOTermsView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser, IsAdminRole]

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        record = ASTOPEngagement.objects.filter(lead=lead).first()
        if record is None:
            return Response({"leadId": str(lead.id), "governedTerms": None})
        scope = record.lo_scope if isinstance(record.lo_scope, dict) else {}
        terms = scope.get("governed_terms") if isinstance(scope.get("governed_terms"), dict) else None
        return Response({"leadId": str(lead.id), "governedTerms": terms})

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        serializer = GovernedLOTermsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = set_governed_lo_terms(lead, by=request.user, **serializer.validated_data)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"gate": str(exc)}) from exc
        return Response({"leadId": str(lead.id), "governedTerms": result.terms, "changed": result.changed})
