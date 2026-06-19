"""
Email views (JWT — Surface 2).

    GET  /emails/              list email logs (most recent first); ?lead_id= to filter
    POST /emails/send/         send an ad-hoc email — lead-scoped (leadId) or by recipient (to)
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.emails.models import EmailLog
from apps.emails.serializers import EmailLogSerializer, SendEmailSerializer
from apps.emails.services.visitor_email_builder import build_visitor_email
from apps.leads.models import Lead


class EmailViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = EmailLog.objects.all().select_related("lead")
    serializer_class = EmailLogSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get_queryset(self):
        qs = super().get_queryset()
        lead_id = self.request.query_params.get("lead_id")
        if lead_id:
            qs = qs.filter(lead_id=lead_id)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = EmailLogSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def send(self, request):
        serializer = SendEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        from rest_framework.generics import get_object_or_404

        lead = None
        if data.get("leadId"):
            lead = get_object_or_404(Lead, pk=data["leadId"])

        log = build_visitor_email(
            lead,
            subject=data["subject"],
            body=data["body"],
            to_email=data.get("to") or None,
            cc=data.get("cc") or [],
            attachments=data.get("attachments") or [],
            scheduled_at=data.get("scheduledAt"),
        )

        scheduled = bool(data.get("scheduledAt"))
        # Anything not delivered inline (scheduled, or delivery disabled) is queued.
        queued = scheduled or not getattr(settings, "ENABLE_EMAIL_DELIVERY", False)
        return Response(
            {"ok": True, "queued": queued, "scheduled": scheduled, "id": str(log.id)}
        )
