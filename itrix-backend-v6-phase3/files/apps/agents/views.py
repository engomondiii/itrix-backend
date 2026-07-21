"""
Agent views (Phase 1 — partial mount).

    POST agents/{key}/run/   TEAM, behind ENABLE_AGENTS — invoke an agent against a
                             lead and return its governed output. This is the seam the
                             S2 console uses; the approval-queue routes arrive in P3.

When ENABLE_AGENTS is off the endpoint returns 503 so nothing runs before the flag is
verified (the funnel's own agent usage goes through the runtime with its own gating).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.serializers import AgentRunRequestSerializer
from apps.agents.services.context import AgentContext, PLANE_TEAM
from apps.agents.services.registry import available_keys
from apps.agents.services.runtime import run_agent
from apps.core.permissions import IsDashboardUser

logger = logging.getLogger("itrix")


class AgentRunView(APIView):
    """POST agents/{key}/run/ — TEAM, gated by ENABLE_AGENTS."""

    permission_classes = [IsDashboardUser]

    def post(self, request, key: str):
        if not getattr(settings, "ENABLE_AGENTS", False):
            return Response(
                {"detail": "Agents are not enabled."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if key not in available_keys():
            return Response({"detail": f"Unknown agent: {key}"}, status=status.HTTP_404_NOT_FOUND)

        ser = AgentRunRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from apps.leads.models import Lead

        lead = get_object_or_404(Lead, id=data["lead_id"]) if data.get("lead_id") else None
        if lead is not None:
            ctx = AgentContext.from_lead(lead, context_label=data.get("context_label", "diagnosis"), plane=PLANE_TEAM)
        else:
            ctx = AgentContext(plane=PLANE_TEAM, context_label=data.get("context_label", "diagnosis"))
        if data.get("message"):
            ctx = AgentContext(**{**ctx.__dict__, "extra": {**ctx.extra, "message": data["message"]}})

        output = run_agent(ctx=ctx, agent_key=key)
        return Response(
            {
                "agentKey": key,
                "usedAi": output.used_ai,
                "governanceStatus": output.governance_status,
                "claimLevel": output.claim_level,
                "output": output.payload,
                "chunkIds": output.chunk_ids,
            },
            status=status.HTTP_200_OK,
        )


# ═════════════════════════════════════════════════════════════════════════════
# Phase 3 — Team console · Approval queue · Cockpit (TEAM plane)
# ═════════════════════════════════════════════════════════════════════════════
from rest_framework.permissions import IsAuthenticated  # noqa: E402

from apps.authentication.permissions import IsGovernanceAdmin  # noqa: E402


# ── Team console ──────────────────────────────────────────────────────────────
class ConsoleConversationListView(APIView):
    """GET console/conversations/ — TEAM. Active conversations for the console."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        from apps.conversations.models import Conversation
        from apps.conversations.serializers import TeamConversationSummarySerializer

        qs = Conversation.objects.filter(is_active=True).order_by("-last_message_at")[:200]
        return Response(TeamConversationSummarySerializer(qs, many=True).data)


class ConsoleMessageView(APIView):
    """
    POST console/conversations/{id}/message/ — TEAM.

    A team→client message. It is governed exactly like an agent message: auto-approved
    delivers; L4/L5 (or violations) hold + queue for a (second) approver.
    """

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def post(self, request, conversation_id):
        from apps.conversations.models import Conversation
        from apps.conversations.services import fan_out, ingest

        conv = get_object_or_404(Conversation, id=conversation_id)
        body = (request.data.get("body") or request.data.get("message") or "").strip()
        if not body:
            return Response({"detail": "body is required."}, status=status.HTTP_400_BAD_REQUEST)

        claim_level = int(request.data.get("claimLevel", 1) or 1)
        msg = ingest.ingest_team_message(conv, user=request.user, body=body)
        msg.claim_level = claim_level
        msg.save(update_fields=["claim_level", "updated_at"])
        final_status = fan_out.govern_and_broadcast(msg)
        return Response(
            {"messageId": str(msg.id), "governanceStatus": final_status},
            status=status.HTTP_201_CREATED,
        )


# ── Approval queue ──────────────────────────────────────────────────────────
class ApprovalQueueView(APIView):
    """GET agents/approval-queue/ — TEAM. The pending/awaiting-second approval requests."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        from apps.governance.models import ApprovalRequest, ApprovalStatus
        from apps.governance.serializers import ApprovalRequestSerializer

        qs = ApprovalRequest.objects.filter(
            status__in=[ApprovalStatus.PENDING, ApprovalStatus.AWAITING_SECOND]
        ).order_by("-created_at")
        return Response(ApprovalRequestSerializer(qs, many=True).data)


class ApprovalActionView(APIView):
    """
    POST agents/approval/{id}/{action}/ — TEAM (governance admin).

    action ∈ {approve, edit, reject}. Applies the L4/L5 second-approver rule via the
    approval_router; on final approval the held message is delivered.
    """

    permission_classes = [IsAuthenticated, IsGovernanceAdmin]

    def post(self, request, approval_id, action):
        from apps.governance.models import ApprovalRequest
        from apps.governance.serializers import ApprovalActionSerializer, ApprovalRequestSerializer
        from apps.governance.services import approval_router

        req = get_object_or_404(ApprovalRequest, id=approval_id)
        ser = ApprovalActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            if action == "approve":
                approval_router.approve(req, actor=request.user, final_body=data.get("body") or None)
            elif action == "edit":
                body = data.get("body")
                if not body:
                    return Response({"detail": "body is required to edit."}, status=status.HTTP_400_BAD_REQUEST)
                approval_router.edit(req, actor=request.user, new_body=body)
            elif action == "reject":
                approval_router.reject(req, actor=request.user, reason=data.get("reason", ""))
            else:
                return Response({"detail": f"Unknown action: {action}"}, status=status.HTTP_400_BAD_REQUEST)
        except approval_router.ApprovalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        req.refresh_from_db()
        return Response(ApprovalRequestSerializer(req).data, status=status.HTTP_200_OK)


# ── Agent-run audit ───────────────────────────────────────────────────────────
class AgentRunListView(APIView):
    """GET agents/runs/ — TEAM. Recent agent-run audit records (most recent first)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        from apps.agents.models import AgentRun
        from apps.agents.serializers import AgentRunSerializer

        qs = AgentRun.objects.all().order_by("-created_at")[:200]
        return Response(AgentRunSerializer(qs, many=True).data)


# ── Cockpit ───────────────────────────────────────────────────────────────────
class CockpitLeadView(APIView):
    """GET cockpit/leads/{id}/ — TEAM. The internal per-lead read (signals never leave the team plane)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request, lead_id):
        from apps.leads.models import Lead

        lead = get_object_or_404(Lead, id=lead_id)
        pitch = {}
        try:
            from apps.analytics.services.pitch_engagement import pitch_engagement_for_lead

            pitch = pitch_engagement_for_lead(lead)
        except Exception:  # noqa: BLE001
            pitch = {}

        read = self._visitor_read(lead)
        return Response(
            {
                "leadId": str(lead.id),
                "company": lead.company,
                "tier": lead.tier,
                "score": lead.score,
                "journeyState": lead.journey_state,
                "productRoute": lead.product_route_display,
                "commercialPath": lead.commercial_path_display,
                "valueDelivered": getattr(lead, "value_delivered_at", None) is not None,
                "pitchEngagement": pitch,
                # The richer internal "read" (deterministic; team plane only — these
                # signals never leave the team plane / never reach a visitor).
                **read,
            }
        )

    @staticmethod
    def _visitor_read(lead) -> dict:
        """Deterministic internal visitor-read derived from the lead (no LLM)."""
        from apps.journey.models import JourneyState

        def clamp(n: float) -> int:
            return max(0, min(100, int(round(n))))

        score = lead.score or 0
        route = (getattr(lead, "product_route", "") or "").lower()
        special = getattr(lead, "special_rights", "") or ""
        has_special = special not in ("", "None", "none")
        pain = getattr(lead, "primary_pain", "") or ""

        if "core" in route:
            visitor_type = "Semiconductor / Hardware partner"
        elif "both" in route:
            visitor_type = "Strategic executive"
        elif "general" in route:
            visitor_type = "Curious visitor"
        else:
            visitor_type = "Cloud / AI infrastructure"

        # Updated for the ten-state ladder (Phase 3 removed CLIENT and ENGAGED).
        ladder_by_state = {
            JourneyState.ARRIVED.value: "Review",
            JourneyState.IN_REVIEW.value: "Review",
            JourneyState.DIAGNOSED.value: "Review",
            JourneyState.CLIENT_PAGE.value: "Review",
            JourneyState.INVITED.value: "Assessment",
            JourneyState.NDA_REVIEW.value: "Assessment",
            JourneyState.ASSESSMENT.value: "Assessment",
            JourneyState.POC.value: "PoC",
            JourneyState.INTEGRATION.value: "Integration",
            JourneyState.CUSTOMER_SUCCESS.value: "Customer success",
            JourneyState.DORMANT.value: "Review",
        }

        return {
            "pain": pain or None,
            "gain": "Lower compute cost at the same SLA, validated through evaluation.",
            "visitorType": visitor_type,
            "buyerPsychology": (
                "Buys validated evidence, not claims — reassured by a scoped paid "
                "assessment before commitment."
            ),
            "objectionSignals": ["Wants proof before any commitment"] if score < 60 else [],
            "readiness": {
                "nda": clamp(score - 8),
                "assessment": clamp(score),
                "poc": clamp(score - 18),
            },
            # Internal directional signal ONLY — never a prediction, never shown to a visitor.
            "licenseOutProbability": clamp(score + (18 if has_special else 0)),
            "ladderStage": ladder_by_state.get(lead.journey_state, "Review"),
        }


class CockpitNextActionView(APIView):
    """
    GET cockpit/leads/{id}/next-action/ — TEAM.

    ── PASSES THROUGH nba_precedence (§11.1) ────────────────────────────────
    The portal path and this cockpit path call the SAME rule, so a customer and an
    operator can never see contradictory guidance. If the rule were implemented twice
    they would drift, and the first symptom would be a customer being sold to while
    their operator was looking at an unresolved outage.

    The response carries ``suppressionReason`` — INTERNAL-ONLY, and the reason this
    endpoint is team-gated. An operator who sees "no expansion action" with no
    explanation assumes the system is broken and works around it.
    """

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request, lead_id):
        from apps.governance.services import nba_precedence
        from apps.journey.services.gate import account_invite_allowed
        from apps.leads.models import Lead

        lead = get_object_or_404(Lead, id=lead_id)
        state = lead.journey_state

        decision = nba_precedence.for_lead(lead, self._candidates(lead))
        action, reason = self._state_action(lead, state, account_invite_allowed(lead))

        payload = {
            "leadId": str(lead.id),
            "state": state,
            # The deterministic, state-derived action — unchanged from v4.0 so existing
            # cockpit behaviour is preserved.
            "nextAction": action,
            "reason": reason,
            # The governed recommendation, with its suppression reason.
            **decision.to_team_payload(),
        }
        return Response(payload)

    @staticmethod
    def _candidates(lead):
        try:
            from apps.agents.services.strategy import nba_candidates

            return nba_candidates(lead)
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _state_action(lead, state, invite_allowed: bool) -> tuple[str, str]:
        """
        The state-derived action.

        Updated for the ten-state ladder: the deprecated CLIENT and ENGAGED members were
        removed in Phase 3, so this maps the live vocabulary. ``normalize_state`` handles
        any stale row so an un-migrated record still resolves rather than falling to the
        generic branch.
        """
        from apps.journey.models import JourneyState, normalize_state

        state = normalize_state(state)

        if state in (JourneyState.ARRIVED.value, JourneyState.IN_REVIEW.value):
            return "await_diagnosis", "The review is still in progress."
        if state == JourneyState.DIAGNOSED.value:
            return "reveal_client_page", "Value delivered — reveal the customized client page."
        if state == JourneyState.CLIENT_PAGE.value:
            if invite_allowed:
                return "send_account_invite", "Lead passed the invite gate — send the workspace invite."
            return "nurture", "Not yet invite-eligible — nurture until a stronger signal appears."
        if state == JourneyState.INVITED.value:
            return "await_claim", "Invite sent — awaiting account creation."
        if state == JourneyState.NDA_REVIEW.value:
            return "propose_evaluation", "Workspace created — progress the NDA and propose a scoped assessment."
        if state == JourneyState.ASSESSMENT.value:
            return "run_assessment", "Paid assessment in progress — deliver the Boundary Waste Map."
        if state == JourneyState.POC.value:
            return "run_poc", "PoC in progress — report results against the agreed KPIs."
        if state == JourneyState.INTEGRATION.value:
            return "close_integration", "Integration underway — progress the commercial decisions."
        if state == JourneyState.CUSTOMER_SUCCESS.value:
            return "customer_success", "Contracted customer — outcomes and support come first."
        if state == JourneyState.DORMANT.value:
            return "reactivate", "Dormant — re-engage if a stronger signal returns."
        return "review", "No specific action determined."
