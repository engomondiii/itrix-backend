"""
Template views (JWT — Surface 2).

    GET/POST       /templates/            list (filter by ?kind=) + create
    GET/PATCH/DEL  /templates/{id}/       retrieve / update / delete

Writes require a non-viewer; delete requires admin.
"""

from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsAdminOrReadOnly, IsDashboardUser, IsNotViewer
from apps.templates_library.models import Template
from apps.templates_library.serializers import TemplateSerializer


class TemplateViewSet(viewsets.ModelViewSet):
    queryset = Template.objects.all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_queryset(self):
        qs = super().get_queryset()
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        if self.action == "destroy":
            return [IsAuthenticated(), IsDashboardUser(), IsAdminOrReadOnly()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = TemplateSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})
