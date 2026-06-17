"""
Reporting views (JWT — Surface 2).

    GET  /reporting/             list reports (most recent first)
    POST /reporting/             generate a report for {month} (default: current month)
    GET  /reporting/{id}/        retrieve a report
    GET  /reporting/{id}/export/ export markdown ({format=md})
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.reporting.models import MonthlyReport
from apps.reporting.serializers import GenerateReportSerializer, MonthlyReportSerializer
from apps.reporting.services.report_exporter import to_markdown
from apps.reporting.services.report_generator import generate_monthly_report


class ReportingViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = MonthlyReport.objects.all()
    serializer_class = MonthlyReportSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = MonthlyReportSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    def create(self, request, *args, **kwargs):
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data.get("month") or None
        report = generate_monthly_report(month=month)
        return Response(MonthlyReportSerializer(report).data, status=201)

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        report = self.get_object()
        return Response({"month": report.month, "format": "md", "content": to_markdown(report)})
