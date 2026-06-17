"""
NDA views (JWT — Surface 2).

    GET   /nda/                 list NDA records
    GET   /nda/{id}/            retrieve one
    PATCH /nda/{id}/            update status / checklist
    POST  /nda/{id}/send/       mark sent
    POST  /nda/{id}/sign/       mark signed (records signedAt, notifies, advances lead)
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.nda.models import NDARecord, NDAStatus
from apps.nda.serializers import ChecklistUpdateSerializer, NDARecordSerializer


class NDAViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = NDARecord.objects.all().select_related("lead")
    serializer_class = NDARecordSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action in {"update", "partial_update", "send", "sign"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = NDARecordSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        nda = self.get_object()
        nda.status = NDAStatus.SENT
        nda.sent_at = timezone.now()
        nda.save(update_fields=["status", "sent_at", "updated_at"])
        return Response(NDARecordSerializer(nda).data)

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        nda = self.get_object()
        nda.status = NDAStatus.SIGNED
        nda.signed_at = timezone.now()
        nda.save(update_fields=["status", "signed_at", "updated_at"])
        # Notify + log on the lead timeline.
        try:
            from apps.notifications.services.notification_creator import notify_nda_signed

            notify_nda_signed(nda)
        except Exception:  # noqa: BLE001
            pass
        return Response(NDARecordSerializer(nda).data)
