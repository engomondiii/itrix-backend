"""
Evaluation views (JWT — Surface 2).

    GET   /evaluations/            list
    POST  /evaluations/            create from {lead_id}
    GET   /evaluations/{id}/       retrieve
    PATCH /evaluations/{id}/       update status / kpis
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.evaluations.models import Evaluation
from apps.evaluations.serializers import CreateEvaluationSerializer, EvaluationSerializer
from apps.evaluations.services.evaluation_creator import create_evaluation_for_lead
from apps.leads.models import Lead


class EvaluationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Evaluation.objects.all().select_related("lead")
    serializer_class = EvaluationSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = EvaluationSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    def create(self, request, *args, **kwargs):
        serializer = CreateEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = get_object_or_404(Lead, pk=serializer.validated_data["lead_id"])
        ev = create_evaluation_for_lead(lead)
        return Response(EvaluationSerializer(ev).data, status=201)
