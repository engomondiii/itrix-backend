"""
NDA views (JWT — Surface 2).

The dashboard addresses NDAs by their **lead id**, not the NDA pk:

    GET   /nda/                   list NDA records (paginated, ?status= & ?search=)
    GET   /nda/{leadId}/          retrieve one (by lead)
    PATCH /nda/{leadId}/          update status / checklist
    POST  /nda/{leadId}/prepare/  edit the document (docType/body/signerName/signerEmail)
    POST  /nda/{leadId}/send/     mark sent (signerName/signerEmail, records sentAt)
    POST  /nda/{leadId}/sign/     mark signed (records signedAt, notifies, advances lead)
    POST  /nda/{leadId}/decline/  mark declined (reason → declineReason)
    POST  /nda/{leadId}/expire/   mark expired

All retrieve/action lookups resolve the NDA via its ``lead`` relation.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.pagination import StandardResultsPagination
from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.nda.models import NDADocType, NDARecord, NDAStatus
from apps.nda.serializers import NDAListSerializer, NDARecordSerializer


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
    pagination_class = StandardResultsPagination
    # The router exposes the lookup as `pk`; resolve it against `lead_id`.
    lookup_field = "lead_id"
    lookup_url_kwarg = "pk"

    def get_permissions(self):
        if self.action in {"update", "partial_update", "prepare", "send", "sign", "decline", "expire"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    def filter_queryset(self, queryset):
        params = self.request.query_params
        status_param = params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        search = params.get("search")
        if search:
            queryset = queryset.filter(
                Q(lead_name__icontains=search)
                | Q(company__icontains=search)
                | Q(signer_name__icontains=search)
                | Q(signer_email__icontains=search)
            )
        return queryset

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            data = NDAListSerializer(page, many=True).data
            return self.get_paginated_response(data)
        data = NDAListSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=True, methods=["post"])
    def prepare(self, request, pk=None):
        """Edit the document in place; status stays ``required``."""
        nda = self.get_object()
        data = request.data
        update_fields = ["updated_at"]
        doc_type = data.get("docType")
        if doc_type in NDADocType.values:
            nda.doc_type = doc_type
            update_fields.append("doc_type")
        if "body" in data:
            nda.body = data.get("body") or ""
            update_fields.append("body")
        if "signerName" in data:
            nda.signer_name = data.get("signerName") or ""
            update_fields.append("signer_name")
        if "signerEmail" in data:
            nda.signer_email = data.get("signerEmail") or ""
            update_fields.append("signer_email")
        nda.save(update_fields=update_fields)
        return Response(NDARecordSerializer(nda).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        nda = self.get_object()
        data = request.data
        signer_email = str(data.get("signerEmail") or "").strip()
        if not signer_email:
            return Response(
                {"detail": "A signer email is required to send the NDA"}, status=400
            )
        nda.signer_email = signer_email
        signer_name = data.get("signerName")
        if signer_name is not None:
            nda.signer_name = str(signer_name).strip()
        nda.status = NDAStatus.SENT
        nda.sent_at = timezone.now()
        nda.save(
            update_fields=["status", "sent_at", "signer_name", "signer_email", "updated_at"]
        )
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

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        nda = self.get_object()
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "A decline reason is required"}, status=400)
        nda.status = NDAStatus.DECLINED
        nda.decline_reason = reason
        nda.save(update_fields=["status", "decline_reason", "updated_at"])
        return Response(NDARecordSerializer(nda).data)

    @action(detail=True, methods=["post"])
    def expire(self, request, pk=None):
        nda = self.get_object()
        nda.status = NDAStatus.EXPIRED
        nda.save(update_fields=["status", "updated_at"])
        return Response(NDARecordSerializer(nda).data)
