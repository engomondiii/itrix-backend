"""
Reporting views (JWT — Surface 2).

    GET    /reporting/                            list reports (most recent first)
    POST   /reporting/                            generate a report for {month} (default: current month)
    POST   /reporting/generate/                   generate a report for {month} (default: current month)
    GET    /reporting/{id}/                        retrieve a report
    DELETE /reporting/{id}/                        delete a report
    GET    /reporting/{id}/sections/               list a report's sections
    POST   /reporting/{id}/sections/               append a section {title, body}
    PATCH  /reporting/{id}/sections/{sectionId}/   update a section's title/body
    DELETE /reporting/{id}/sections/{sectionId}/   remove a section
    GET    /reporting/{id}/export/                 export markdown ({format=md})
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.reporting.models import MonthlyReport
from apps.reporting.serializers import (
    GenerateReportSerializer,
    MonthlyReportSerializer,
    SectionInputSerializer,
    SectionPatchSerializer,
)
from apps.reporting.services.report_exporter import to_markdown
from apps.reporting.services.report_generator import generate_monthly_report
from apps.reporting.services.report_sections import (
    add_section,
    remove_section,
    update_section,
)


class ReportingViewSet(
    mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = MonthlyReport.objects.all()
    serializer_class = MonthlyReportSerializer
    permission_classes = [IsAuthenticated, IsDashboardUser]

    # Actions that mutate require a non-viewer dashboard user.
    _write_actions = {"create", "generate", "destroy", "sections", "section_detail"}

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = MonthlyReportSerializer(qs, many=True).data
        return Response({"results": data, "count": len(data)})

    def create(self, request, *args, **kwargs):
        return self._generate(request)

    def get_permissions(self):
        if self.action in self._write_actions:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    def _generate(self, request):
        serializer = GenerateReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data.get("month") or None
        report = generate_monthly_report(month=month)
        return Response(MonthlyReportSerializer(report).data, status=201)

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        return self._generate(request)

    @action(detail=True, methods=["get", "post"], url_path="sections")
    def sections(self, request, pk=None):
        report = self.get_object()
        if request.method == "POST":
            serializer = SectionInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            report = add_section(
                report,
                title=serializer.validated_data["title"],
                body=serializer.validated_data["body"],
            )
            return Response(MonthlyReportSerializer(report).data, status=201)
        return Response(report.sections or [])

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"sections/(?P<section_id>[^/.]+)",
    )
    def section_detail(self, request, pk=None, section_id=None):
        report = self.get_object()
        if request.method == "DELETE":
            report = remove_section(report, section_id)
            if report is None:
                return Response({"detail": "Not found"}, status=404)
            return Response(MonthlyReportSerializer(report).data)

        serializer = SectionPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = update_section(
            report,
            section_id,
            title=serializer.validated_data.get("title"),
            body=serializer.validated_data.get("body"),
        )
        if report is None:
            return Response({"detail": "Not found"}, status=404)
        return Response(MonthlyReportSerializer(report).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        report = self.get_object()
        return Response({"month": report.month, "format": "md", "content": to_markdown(report)})
