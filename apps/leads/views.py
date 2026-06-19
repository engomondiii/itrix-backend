"""
Lead views.

``LeadViewSet`` (JWT — Surface 2) provides list/retrieve/create/patch plus the ten
custom actions from the v3 endpoint map:

    POST {id}/assign/     POST {id}/status/      POST {id}/note/
    POST {id}/escalate/   POST {id}/nda/         POST {id}/paid-eval/   POST {id}/poc/
    POST {id}/meeting/
    GET  {id}/summary/    GET  {id}/handoff/      GET  approval-checklist/

``LeadEmailCaptureView`` (PUBLIC — Surface 1) handles ``lead-capture/email/`` and is
wired directly in ``api/v1/urls.py`` (there is no separate lead-capture app).

NDA / paid-eval / PoC records are full apps in Phase 3; in Phase 2 these actions record
the intent on the lead timeline and advance status, so the dashboard buttons work and
the history is accurate. Phase 3 swaps the bodies to create the real records.
"""

from __future__ import annotations

import logging
import uuid

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead, LeadActivity, LeadStatus
from apps.leads.serializers import (
    AssignSerializer,
    EscalateSerializer,
    LeadDetailSerializer,
    LeadEmailCaptureSerializer,
    LeadListSerializer,
    LeadUpdateSerializer,
    MeetingSerializer,
    NoteSerializer,
    StatusSerializer,
)
from apps.leads.services.exclusive_flag_handler import approval_checklist
from apps.leads.services.handoff_memo_generator import generate_handoff_memo
from apps.leads.services.lead_escalator import escalate_lead
from apps.leads.services.lead_summary_generator import generate_lead_summary
from apps.leads.services.lead_updater import (
    add_note,
    apply_email_capture,
    assign_owner,
    book_meeting,
    change_status,
)

logger = logging.getLogger("itrix")
User = get_user_model()


class LeadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Lead.objects.all()
        .select_related("owner")
        .prefetch_related("notes", "activities", "meetings")
    )
    permission_classes = [IsAuthenticated, IsDashboardUser]
    http_method_names = ["get", "post", "patch", "head", "options"]

    from apps.leads.filters import LeadFilter  # local import to keep module load order clean

    filterset_class = LeadFilter
    search_fields = ["company", "visitor_name", "email", "industry", "primary_pain"]
    ordering_fields = ["submitted_at", "score", "tier", "status"]
    ordering = ["-submitted_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return LeadListSerializer
        if self.action in {"partial_update", "update"}:
            return LeadUpdateSerializer
        return LeadDetailSerializer

    def get_permissions(self):
        # Writes are blocked for viewer accounts.
        if self.action in {"create", "update", "partial_update"}:
            return [IsAuthenticated(), IsDashboardUser(), IsNotViewer()]
        return super().get_permissions()

    # Support the dashboard's `?sort=&dir=` in addition to DRF `ordering`.
    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        sort = self.request.query_params.get("sort")
        if sort:
            field_map = {
                "submittedAt": "submitted_at",
                "score": "score",
                "tier": "tier",
                "status": "status",
            }
            field = field_map.get(sort, sort)
            direction = "" if self.request.query_params.get("dir", "desc") == "asc" else "-"
            queryset = queryset.order_by(f"{direction}{field}")
        return queryset

    def _actor(self):
        return self.request.user

    def _detail_response(self, lead, *, code=status.HTTP_200_OK):
        return Response(LeadDetailSerializer(lead).data, status=code)

    # ── Custom actions ───────────────────────────────────────────────────────
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def assign(self, request, pk=None):
        lead = self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        owner_ref = serializer.validated_data.get("owner")
        owner = None
        if owner_ref:
            owner = self._resolve_owner(owner_ref)
            if owner is None:
                from apps.core.exceptions import ITrixError

                raise ITrixError(f"Unknown owner: {owner_ref!r}")
        assign_owner(lead, owner=owner, by=self._actor())
        return self._detail_response(lead)

    @staticmethod
    def _resolve_owner(owner_ref: str):
        """Resolve an owner by email / name, or by UUID id when the ref looks like one."""
        owner = (
            User.objects.filter(email__iexact=owner_ref).first()
            or User.objects.filter(name__iexact=owner_ref).first()
        )
        if owner is None:
            try:
                uuid.UUID(str(owner_ref))
            except (ValueError, TypeError):
                return None
            owner = User.objects.filter(id=owner_ref).first()
        return owner

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def status(self, request, pk=None):
        lead = self.get_object()
        serializer = StatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change_status(lead, status=serializer.validated_data["status"], by=self._actor())
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def note(self, request, pk=None):
        lead = self.get_object()
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_note(lead, body=serializer.validated_data["body"], by=self._actor())
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def meeting(self, request, pk=None):
        """Book a meeting, advance status to "Meeting Booked", and log it."""
        lead = self.get_object()
        serializer = MeetingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        book_meeting(
            lead,
            scheduled_at=data["scheduled_at"],
            duration_mins=data.get("duration_mins", 30),
            attendee=data.get("attendee", ""),
            location=data.get("location", ""),
            notes=data.get("notes", ""),
            by=self._actor(),
        )
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def escalate(self, request, pk=None):
        lead = self.get_object()
        serializer = EscalateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        escalate_lead(
            lead,
            reason=serializer.validated_data.get("reason", ""),
            priority=serializer.validated_data.get("priority", "normal"),
            by=self._actor(),
        )
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def nda(self, request, pk=None):
        """Mark NDA required, create the NDA record (Phase 3), and advance status."""
        lead = self.get_object()
        change_status(lead, status=LeadStatus.NDA, by=self._actor())
        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.NDA,
            label="NDA marked required.",
            by=self._actor(),
            by_name=self._actor().display_name,
        )
        # Phase 3: create the real NDA record (lazy import keeps leads independent of nda).
        try:
            from apps.nda.services.nda_creator import create_nda_for_lead

            create_nda_for_lead(lead)
        except Exception:  # noqa: BLE001
            pass
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], url_path="paid-eval", permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def paid_eval(self, request, pk=None):
        """Create the paid Evaluation (Phase 3) and advance status."""
        lead = self.get_object()
        change_status(lead, status=LeadStatus.EVALUATION, by=self._actor())
        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.PAID_EVAL,
            label="Paid evaluation initiated.",
            by=self._actor(),
            by_name=self._actor().display_name,
        )
        # Capture the paid-eval setup fields on the Evaluation record (best-effort,
        # cross-app — lazy import keeps leads independent of the evaluations app).
        try:
            from apps.evaluations.services.evaluation_creator import create_evaluation_for_lead

            payload = {
                k: request.data.get(k)
                for k in ("scope", "fee", "timeline")
                if request.data.get(k) is not None
            }
            create_evaluation_for_lead(lead, **payload)
        except Exception:  # noqa: BLE001
            pass
        return self._detail_response(lead)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsDashboardUser, IsNotViewer])
    def poc(self, request, pk=None):
        """Create the PoC record (Phase 3) and advance status."""
        lead = self.get_object()
        change_status(lead, status=LeadStatus.POC, by=self._actor())
        LeadActivity.objects.create(
            lead=lead,
            type=LeadActivity.ActivityType.POC,
            label="Proof-of-concept initiated.",
            by=self._actor(),
            by_name=self._actor().display_name,
        )
        # Capture the PoC setup fields on the PoC record (best-effort, cross-app — lazy
        # import keeps leads independent of the pocs app). The dashboard sends camelCase
        # keys; map them to the creator's snake_case kwargs.
        try:
            from apps.pocs.services.poc_creator import create_poc_for_lead

            key_map = {
                "scope": "scope",
                "durationWeeks": "duration_weeks",
                "successMetrics": "success_metrics",
                "startDate": "start_date",
            }
            payload = {
                snake: request.data.get(camel)
                for camel, snake in key_map.items()
                if request.data.get(camel) is not None
            }
            create_poc_for_lead(lead, **payload)
        except Exception:  # noqa: BLE001
            pass
        return self._detail_response(lead)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Internal AI summary text for the lead."""
        lead = self.get_object()
        text = lead.compute_bottleneck or generate_lead_summary(
            prompt=(lead.review_session.prompt if lead.review_session else ""),
            pressures=(lead.review_session.pressure_areas if lead.review_session else []),
            product_route=lead.product_route,
            tier=lead.tier,
        )
        return Response({"lead_id": str(lead.id), "summary": text})

    @action(detail=True, methods=["get"])
    def handoff(self, request, pk=None):
        """Offline handoff memo (plain text in JSON)."""
        lead = self.get_object()
        return Response({"lead_id": str(lead.id), "memo": generate_handoff_memo(lead)})

    @action(detail=False, methods=["get"], url_path="approval-checklist")
    def approval_checklist(self, request):
        """Exclusive-approval checklist (static 7-item list)."""
        return Response({"items": approval_checklist()})


class LeadEmailCaptureView(APIView):
    """
    PUBLIC — Surface 1 email capture (``lead-capture/email/``).

    Wired directly in api/v1/urls.py. Attaches captured contact details to the lead
    referenced by ``lead_id`` (falling back to the lead for ``session_id``). Always
    returns 200 so the public confirmation is clean even if the lead can't be found.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request):
        serializer = LeadEmailCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        lead = None
        if data.get("lead_id"):
            lead = Lead.objects.filter(pk=data["lead_id"]).first()
        if lead is None and data.get("session_id"):
            lead = Lead.objects.filter(review_session_id=data["session_id"]).first()

        if lead is not None:
            apply_email_capture(
                lead,
                email=data.get("email", ""),
                name=data.get("name", ""),
                company=data.get("company", ""),
                source=data.get("source", "web"),
            )
            return Response({"ok": True, "lead_id": str(lead.id)})

        # No lead yet (e.g. captured before qualify) — acknowledge cleanly.
        logger.info("Email capture with no matching lead (lead_id=%s session_id=%s)", data.get("lead_id"), data.get("session_id"))
        return Response({"ok": True, "lead_id": data.get("lead_id")})
