"""Result-page views with server-side, session-bound client access."""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.backends import ClientJWTAuthentication
from apps.clients.models import Client
from apps.core.permissions import IsDashboardUser, IsNotViewer
from apps.leads.models import Lead
from apps.result_page.models import ResultPage
from apps.result_page.serializers import ResultPageSerializer
from apps.result_page.services.result_generator import ResultGenerator
from apps.review.models import ReviewSession

logger = logging.getLogger("itrix")

VISITOR_SESSION_COOKIE = "itrix_visitor_session"
VISITOR_SESSION_HEADER = "HTTP_X_ITRIX_SESSION"
CLIENT_PAGE_SESSION_HEADER = "HTTP_X_ITRIX_CLIENT_PAGE_SESSION"


def _visitor_session(request) -> str:
    return (
        (request.META.get(VISITOR_SESSION_HEADER, "") or "").strip()
        or (request.COOKIES.get(VISITOR_SESSION_COOKIE, "") or "").strip()
    )[:64]


def _client(request):
    user = getattr(request, "user", None)
    return user if isinstance(user, Client) else None


def _resolve_lead(lead_ref: str) -> Lead | None:
    lead = Lead.objects.filter(pk=lead_ref).first()
    if lead:
        return lead
    session = ReviewSession.objects.filter(pk=lead_ref).first()
    return Lead.objects.filter(review_session=session).first() if session else None


def _safe_unavailable(code: str = "access_unavailable", http_status: int = status.HTTP_404_NOT_FOUND):
    # Enumeration-safe: expired, wrong browser, reused, revoked and malformed all look alike.
    return Response({"error": {"detail": "This review access is unavailable.", "code": code}}, status=http_status)


class ResultPageDetailView(APIView):
    """TEAM only. Personalized reviews are no longer public by lead UUID."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request, lead_id: str):
        lead = _resolve_lead(lead_id)
        if lead is None:
            return _safe_unavailable()
        result_obj = ResultPage.objects.filter(lead=lead).first()
        if result_obj is None:
            return _safe_unavailable("review_not_ready")
        return Response(ResultPageSerializer(result_obj).data)


class ResultPageGenerateView(APIView):
    permission_classes = [IsAuthenticated, IsDashboardUser, IsNotViewer]

    def post(self, request):
        lead_ref = request.data.get("lead_id")
        if not lead_ref:
            return Response(
                {"error": {"detail": "lead_id is required.", "code": "invalid"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        lead = _resolve_lead(lead_ref)
        if lead is None:
            return _safe_unavailable()
        result_obj, _report = ResultGenerator().generate_for_lead(lead)
        return Response(ResultPageSerializer(result_obj).data, status=status.HTTP_201_CREATED)


class ResultPageAccessExchangeView(APIView):
    """POST an opaque one-time code; return an opaque cookie token to the BFF only."""

    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication]
    throttle_scope = "review_submit"

    def post(self, request):
        from apps.result_page.services.client_access import ClientPageAccessError, exchange

        code = str(request.data.get("code") or "").strip()
        if not code:
            return _safe_unavailable()
        try:
            raw_session, lead = exchange(
                code,
                visitor_session=_visitor_session(request),
                client=_client(request),
            )
        except ClientPageAccessError:
            return _safe_unavailable()

        page = ResultPage.objects.filter(lead=lead, generation_status=ResultPage.GenerationStatus.READY).first()
        if page is None:
            return _safe_unavailable("review_not_ready")
        return Response({"sessionToken": raw_session}, status=status.HTTP_200_OK)


class ResultPageClientView(APIView):
    """GET the completed review through a server-side access session."""

    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request):
        from apps.result_page.services.client_access import ClientPageAccessError, resolve_session

        raw = (request.META.get(CLIENT_PAGE_SESSION_HEADER, "") or "").strip()
        try:
            lead = resolve_session(raw, visitor_session=_visitor_session(request), client=_client(request))
        except ClientPageAccessError:
            return _safe_unavailable()

        result_obj = ResultPage.objects.filter(
            lead=lead, generation_status=ResultPage.GenerationStatus.READY
        ).first()
        if result_obj is None:
            return _safe_unavailable("review_not_ready")
        return Response(ResultGenerator().build_client_page(lead, context="public"), status=status.HTTP_200_OK)


class ResultPageClientChatView(APIView):
    """POST client-review chat through the same server-side access session."""

    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication]
    throttle_scope = "review_submit"

    def post(self, request):
        from apps.result_page.services.client_access import ClientPageAccessError, resolve_session

        raw = (request.META.get(CLIENT_PAGE_SESSION_HEADER, "") or "").strip()
        try:
            lead = resolve_session(raw, visitor_session=_visitor_session(request), client=_client(request))
        except ClientPageAccessError:
            return _safe_unavailable()

        body = (request.data.get("message") or request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"error": {"detail": "message is required.", "code": "invalid"}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.agents.services.context import AgentContext, PLANE_PUBLIC
        from apps.agents.services.runtime import run_concierge
        from apps.conversations.services import fan_out, ingest
        from apps.conversations.services.history import get_or_create_client_page_conversation

        conv = get_or_create_client_page_conversation(lead)
        thread = getattr(conv, "thread", None)
        if thread is None:
            from apps.conversations.models_thread import Thread

            thread = Thread.objects.filter(lead=lead).order_by("-updated_at").first()
        inbound = ingest.ingest_inbound(conv, sender_kind="visitor", body=body, thread=thread)
        fan_out.broadcast_message(inbound)
        session = getattr(lead, "review_session", None)

        # My Review chat is still a public/customer-facing conversation plane.  Do not let
        # it become a bypass around the deterministic confidentiality or protected-function
        # controls enforced on the main conversation route.
        from apps.conversations.services import confidentiality, protected_probe, response_policy, terminology

        locale = getattr(thread, "locale", "") or getattr(session, "locale", "en") or "en"
        intercept = confidentiality.detect(body)
        if intercept.sensitive:
            reply_text = confidentiality.safe_reply(locale=locale)
            reply_msg = ingest.ingest_agent_message(
                conv, agent_key="concierge", body=reply_text, governance_status="auto_approved",
                claim_level=0, meta={"policy_stop": "confidential_input"}, thread=thread,
            )
            fan_out.broadcast_message(reply_msg)
            return Response({
                "reply": reply_text, "suggestNda": False,
                "governanceStatus": "auto_approved", "underReview": False,
            }, status=status.HTTP_200_OK)
        if protected_probe.is_probe(body):
            if thread is not None:
                protected_probe.record(thread)
            reply_text = protected_probe.safe_reply(locale=locale)
            reply_msg = ingest.ingest_agent_message(
                conv, agent_key="concierge", body=reply_text, governance_status="auto_approved",
                claim_level=0, meta={"policy_stop": "protected_probe"}, thread=thread,
            )
            fan_out.broadcast_message(reply_msg)
            return Response({
                "reply": reply_text, "suggestNda": False,
                "governanceStatus": "auto_approved", "underReview": False,
            }, status=status.HTTP_200_OK)

        out = run_concierge(
            AgentContext(
                lead_id=str(lead.id),
                prompt=getattr(session, "prompt", "") or body,
                pressures=list(getattr(session, "pressure_areas", []) or []),
                product_route=lead.product_route,
                license_pathway=lead.commercial_path if lead.commercial_path != "none" else None,
                tier=lead.tier,
                plane=PLANE_PUBLIC,
                context_label="client_page",
                extra={"message": body},
            )
        )
        payload_out = out.payload or {}
        reply_text = terminology.normalise_outbound(payload_out.get("reply", ""))
        reply_text = response_policy.enforce(reply_text, thread=thread)
        reply_msg = ingest.ingest_agent_message(
            conv,
            agent_key="concierge",
            body=reply_text,
            governance_status=out.governance_status,
            claim_level=out.claim_level,
            cited_chunk_ids=out.chunk_ids,
        )
        fan_out.broadcast_message(reply_msg)
        return Response(
            {
                "reply": reply_text if reply_msg.is_deliverable else "",
                "suggestNda": bool(payload_out.get("suggestNda", False)),
                "governanceStatus": out.governance_status,
                "underReview": not reply_msg.is_deliverable,
            },
            status=status.HTTP_200_OK,
        )


class LegacyResultPageTokenView(APIView):
    """Retired reusable bearer-token route. Always fail without inspecting the token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, token: str):
        return _safe_unavailable("legacy_access_retired", status.HTTP_410_GONE)

    def post(self, request, token: str):
        return _safe_unavailable("legacy_access_retired", status.HTTP_410_GONE)
