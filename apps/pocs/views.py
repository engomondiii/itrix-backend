"""
PoC views (JWT — Surface 2).

    GET   /pocs/            list
    POST  /pocs/            create from {lead_id}
    GET   /pocs/{id}/       retrieve
    PATCH /pocs/{id}/       update status / milestones / kpis / risks
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead
from apps.pocs.models import PoC
from apps.pocs.serializers import CreatePoCSerializer, PoCSerializer
from apps.pocs.services.poc_creator import create_poc_for_lead


class PoCViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = PoC.objects.all().select_related("lead")
    serializer_class = PoCSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = PoCSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    def create(self, request, *args, **kwargs):
        serializer = CreatePoCSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = get_object_or_404(Lead, pk=serializer.validated_data["lead_id"])
        poc = create_poc_for_lead(lead)
        return Response(PoCSerializer(poc).data, status=201)
