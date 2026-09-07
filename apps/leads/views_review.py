"""Team-plane human-review API over the existing Lead trust state."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead
from apps.leads.serializers_review import TrustReviewDecisionSerializer
from apps.leads.services.human_review import human_review_snapshot, resolve_trust_review


class TrustReviewView(APIView):
    """Read the safe internal review state; resolve it only as an authorized reviewer."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_permissions(self):
        permissions = [IsAuthenticated(), IsDashboardUser()]
        if self.request.method not in SAFE_METHODS:
            permissions.append(IsNotViewer())
        return permissions

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        return Response(human_review_snapshot(lead))

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, pk=lead_id)
        serializer = TrustReviewDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = resolve_trust_review(
                lead,
                decision=serializer.validated_data["decision"],
                rationale=serializer.validated_data["rationale"],
                by=request.user,
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"review": str(exc)}) from exc
        return Response(human_review_snapshot(result.lead))
