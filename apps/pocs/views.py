"""
PoC views (JWT — Surface 2).

    GET    /pocs/                                  list
    POST   /pocs/                                  create from {lead_id}
    GET    /pocs/{id}/                             retrieve
    PATCH  /pocs/{id}/                             update status / milestones / kpis / risks
    PATCH  /pocs/{id}/kpis/{kpiId}/               update one KPI row in the kpis JSON list
    GET    /pocs/{id}/risks/                       list the risks register
    POST   /pocs/{id}/risks/                       append a new risk (returns the PoC)
    PATCH  /pocs/{id}/risks/{riskId}/             update a risk by id
    DELETE /pocs/{id}/risks/{riskId}/             remove a risk by id
    PATCH  /pocs/{id}/milestones/{milestoneId}/   update a milestone (esp. status)
"""

from __future__ import annotations

import uuid

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.exceptions import ITrixError
from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead
from apps.pocs.models import PoC
from apps.pocs.serializers import CreatePoCSerializer, PoCSerializer
from apps.pocs.services.poc_creator import create_poc_for_lead

MILESTONE_STATUSES = {"pending", "in_progress", "done", "missed"}
RISK_SEVERITIES = {"low", "medium", "high"}


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

    # ── Nested sub-resources ─────────────────────────────────────────────────
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"kpis/(?P<kpi_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer],
    )
    def update_kpi(self, request, pk=None, kpi_id=None):
        """PATCH /pocs/{id}/kpis/{kpiId}/ — update one KPI row in the kpis list."""
        poc = self.get_object()
        kpis = poc.kpis or []
        item = next((k for k in kpis if str(k.get("id")) == str(kpi_id)), None)
        if item is None:
            raise ITrixError("KPI not found.")
        for field in ("category", "metric", "baseline", "target", "result"):
            if field in request.data:
                item[field] = request.data[field]
        poc.kpis = kpis
        poc.save(update_fields=["kpis", "updated_at"])
        return Response(PoCSerializer(poc).data)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path="risks",
    )
    def risks(self, request, pk=None):
        """GET lists the risk register; POST appends a new risk and returns the PoC."""
        poc = self.get_object()
        if request.method == "GET":
            return Response(poc.risks or [])

        # POST — viewer accounts cannot write.
        if not IsNotViewer().has_permission(request, self):
            self.permission_denied(request, message="Viewer accounts cannot modify PoCs.")
        description = str(request.data.get("description") or "").strip()
        severity = str(request.data.get("severity") or "")
        if not description:
            raise ITrixError("Risk description is required.")
        if severity not in RISK_SEVERITIES:
            raise ITrixError("Invalid risk severity.")
        risk = {
            "id": uuid.uuid4().hex,
            "description": description,
            "severity": severity,
            "mitigation": request.data.get("mitigation"),
        }
        risks = poc.risks or []
        risks.append(risk)
        poc.risks = risks
        poc.save(update_fields=["risks", "updated_at"])
        return Response(PoCSerializer(poc).data, status=201)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"risks/(?P<risk_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer],
    )
    def risk_detail(self, request, pk=None, risk_id=None):
        """PATCH updates a risk by id; DELETE removes it. Returns the PoC."""
        poc = self.get_object()
        risks = poc.risks or []
        idx = next(
            (i for i, r in enumerate(risks) if str(r.get("id")) == str(risk_id)), None
        )
        if idx is None:
            raise ITrixError("Risk not found.")

        if request.method == "DELETE":
            risks.pop(idx)
        else:
            item = risks[idx]
            if "description" in request.data:
                item["description"] = request.data["description"]
            if "mitigation" in request.data:
                item["mitigation"] = request.data["mitigation"]
            if "severity" in request.data:
                severity = str(request.data["severity"] or "")
                if severity not in RISK_SEVERITIES:
                    raise ITrixError("Invalid risk severity.")
                item["severity"] = severity
        poc.risks = risks
        poc.save(update_fields=["risks", "updated_at"])
        return Response(PoCSerializer(poc).data)

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"milestones/(?P<milestone_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer],
    )
    def update_milestone(self, request, pk=None, milestone_id=None):
        """PATCH /pocs/{id}/milestones/{milestoneId}/ — update a milestone (esp. status)."""
        poc = self.get_object()
        milestones = poc.milestones or []
        item = next(
            (m for m in milestones if str(m.get("id")) == str(milestone_id)), None
        )
        if item is None:
            raise ITrixError("Milestone not found.")
        if "status" in request.data:
            status_val = str(request.data["status"] or "")
            if status_val not in MILESTONE_STATUSES:
                raise ITrixError("Invalid milestone status.")
            item["status"] = status_val
        if "label" in request.data:
            item["label"] = request.data["label"]
        if "dueAt" in request.data:
            item["dueAt"] = request.data["dueAt"]
        poc.milestones = milestones
        poc.save(update_fields=["milestones", "updated_at"])
        return Response(PoCSerializer(poc).data)
