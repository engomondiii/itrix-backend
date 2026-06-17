"""
Pipeline view (JWT — Surface 2).

    GET /pipeline/   → {stages: [{status, count, leads: [PipelineCardData]}]}

Stages are the 8 dashboard pipeline columns in order. Each card carries an ``overdue`` flag
derived from the lead's open follow-up task being past due. The board reads Lead.status; no
pipeline-specific storage exists.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser
from apps.leads.models import Lead
from apps.pipeline.serializers import PipelineCardSerializer

# The dashboard's pipeline column order (8 visible stages).
PIPELINE_STAGES = [
    "New",
    "Contacted",
    "Meeting Booked",
    "NDA",
    "Evaluation",
    "PoC",
    "Licensed",
    "Closed",
]


class PipelineBoardView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        overdue_lead_ids = self._overdue_lead_ids()
        leads = list(
            Lead.objects.filter(status__in=PIPELINE_STAGES).select_related("owner")
        )
        by_status: dict[str, list] = {s: [] for s in PIPELINE_STAGES}
        for lead in leads:
            by_status.setdefault(lead.status, []).append(lead)

        stages = []
        for status in PIPELINE_STAGES:
            cards = PipelineCardSerializer(
                by_status.get(status, []),
                many=True,
                context={"overdue_lead_ids": overdue_lead_ids},
            ).data
            stages.append({"status": status, "count": len(cards), "leads": cards})

        return Response({"stages": stages})

    @staticmethod
    def _overdue_lead_ids() -> set[str]:
        try:
            from apps.follow_up.services.sla_breach_checker import find_overdue

            return {str(t.lead_id) for t in find_overdue().only("lead_id")}
        except Exception:  # noqa: BLE001
            return set()
