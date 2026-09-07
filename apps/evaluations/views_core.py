"""Team-plane operation for opening a governed ALPHA Core opportunity."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.evaluations.models import Evaluation
from apps.evaluations.serializers import EvaluationSerializer
from apps.evaluations.services.alpha_core_opportunity import open_alpha_core_opportunity


class AlphaCoreOpportunityView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser, IsNotViewer]

    def post(self, request, evaluation_id):
        evaluation = get_object_or_404(Evaluation.objects.select_related("lead"), pk=evaluation_id)
        try:
            result = open_alpha_core_opportunity(evaluation, by=request.user)
        except ValueError as exc:
            raise ValidationError({"gate": str(exc)}) from exc
        return Response(
            {
                "created": result.created,
                "opportunity": EvaluationSerializer(result.opportunity).data,
            },
            status=201 if result.created else 200,
        )
