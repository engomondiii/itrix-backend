"""
Evaluation views (JWT — Surface 2).

    GET   /evaluations/                       list
    POST  /evaluations/                       create from {lead_id}
    GET   /evaluations/{id}/                  retrieve
    PATCH /evaluations/{id}/                  update status / kpis
    PATCH /evaluations/{id}/kpis/{kpiId}/     update one KPI row in the kpis JSON list
"""

from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.exceptions import ITrixError
from apps.core.permissions import IsAdminRole, IsDashboardUser, IsNotViewer
from apps.evaluations.models import Evaluation
from apps.evaluations.serializers import AIFeeDecisionSerializer, CreateEvaluationSerializer, EvaluationSerializer, IWLOverrideSerializer
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


    @action(detail=True, methods=["post"], url_path="ai-fee-decision", permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def ai_fee_decision(self, request, pk=None):
        from apps.leads.services.commercial_progression import record_ai_fee_decision
        ser = AIFeeDecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ev = record_ai_fee_decision(self.get_object(), **ser.validated_data)
        return Response(EvaluationSerializer(ev).data)

    @action(detail=True, methods=["post"], url_path="iwl-override", permission_classes=[IsAuthenticated, IsDashboardUser, IsAdminRole])
    def iwl_override(self, request, pk=None):
        from rest_framework.exceptions import ValidationError
        from apps.leads.services.commercial_progression import record_iwl_override
        ser = IWLOverrideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ev = record_iwl_override(self.get_object(), **ser.validated_data)
        except ValueError as exc:
            raise ValidationError({"fee": str(exc)}) from exc
        return Response(EvaluationSerializer(ev).data)

    @action(detail=True, methods=["post"], url_path="finalize-fee", permission_classes=[IsAuthenticated, IsDashboardUser, IsAdminRole])
    def finalize_fee(self, request, pk=None):
        from apps.leads.services.commercial_progression import finalize_assessment_fee
        ev = finalize_assessment_fee(self.get_object())
        return Response(EvaluationSerializer(ev).data)

    @action(detail=True, methods=["get"], url_path="alpha-core-gate")
    def alpha_core_gate(self, request, pk=None):
        from apps.leads.services.commercial_progression import alpha_core_gate
        decision = alpha_core_gate(self.get_object())
        return Response({"allowed": decision.allowed, "reasons": list(decision.reasons)})

    # ── Nested sub-resources ─────────────────────────────────────────────────
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"kpis/(?P<kpi_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer],
    )
    def update_kpi(self, request, pk=None, kpi_id=None):
        """PATCH /evaluations/{id}/kpis/{kpiId}/ — update one KPI row in the kpis list."""
        ev = self.get_object()
        kpis = ev.kpis or []
        item = next((k for k in kpis if str(k.get("id")) == str(kpi_id)), None)
        if item is None:
            raise ITrixError("KPI not found.")
        for field in ("category", "metric", "target", "result"):
            if field in request.data:
                item[field] = request.data[field]
        ev.kpis = kpis
        ev.save(update_fields=["kpis", "updated_at"])
        return Response(EvaluationSerializer(ev).data)
