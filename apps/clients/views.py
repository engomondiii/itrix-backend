"""
Client views.

Phase 1 exposes the ONE public client-plane endpoint that is live now:

    POST accounts/invite/{token}/claim/   PUBLIC — consume an account_invite token,
                                          create the Client, and mint a client-JWT
                                          (reveal ③). Mounted at the API root so the
                                          path is /api/v1/accounts/invite/{token}/claim/.

The portal auth + data endpoints (client/auth/login, client/me, portal/*) arrive in
Phase 2 and will live in this app too. The invite-claim view is the seam that turns an
invited visitor into an account holder.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.serializers import (
    ClientIdentitySerializer,
    InviteClaimRequestSerializer,
)
from apps.clients.services.invite import InviteError, claim_invite
from apps.clients.tokens import build_tokens_for_client

logger = logging.getLogger("itrix")


class InviteClaimView(APIView):
    """POST accounts/invite/{token}/claim/ — PUBLIC (the token IS the credential)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, token: str):
        ser = InviteClaimRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            client, requires_password_set = claim_invite(
                token,
                email=data.get("email") or None,
                password=data.get("password") or None,
                full_name=data.get("full_name", ""),
                organization=data.get("organization", ""),
                role=data.get("role", ""),
                # v6.0 §2.2: the visitor's anonymous threads follow them into the
                # workspace, claimed inside the same transaction as the nonce burn.
                visitor_session=_visitor_session_from(request),
                # v7.2 — checked against the versions this deployment serves. A mismatch is
                # logged loudly: it means the visitor read something other than what binds
                # them (R62).
                assent_versions=data.get("assent") or [],
            )
        except InviteError as exc:
            # 404 to avoid leaking whether a given token ever existed.
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        tokens = build_tokens_for_client(client)
        body = {
            "client": ClientIdentitySerializer(client).data,
            "requiresPasswordSet": requires_password_set,
            **tokens,
        }
        if requires_password_set:
            # The invitation has already been verified and consumed. Bridge into the
            # dedicated password-set capability instead of reusing the invite token for a
            # second purpose. The BFF stores this value in an httpOnly transient cookie.
            from apps.clients.services.set_password import issue_set_password_token

            body["setPasswordToken"] = issue_set_password_token(client)
        return Response(body, status=status.HTTP_201_CREATED)


# ═════════════════════════════════════════════════════════════════════════════
# Phase 2 — client-plane auth + portal endpoints (client-JWT)
# ═════════════════════════════════════════════════════════════════════════════
from django.conf import settings  # noqa: E402
from django.shortcuts import get_object_or_404  # noqa: E402

from apps.clients.models import Client  # noqa: E402
from apps.clients.backends import ClientJWTAuthentication  # noqa: E402
from apps.clients.permissions import IsAuthenticatedClient  # noqa: E402
from apps.clients.serializers import (  # noqa: E402
    ClientLoginRequestSerializer,
    ClientTokenRefreshRequestSerializer,
    PortalDataRoomSerializer,
    PortalEvaluationSerializer,
    PortalSettingsPatchSerializer,
    PortalOverviewSerializer,
    PortalPoCSerializer,
)
from apps.clients.services.client_creator import authenticate_client  # noqa: E402
from apps.clients.tokens import (  # noqa: E402
    build_tokens_for_client,
    decode_client_token,
    token_matches_current_session,
)
from apps.clients.throttles import AUTH_THROTTLES  # noqa: E402


def _portal_enabled_response():
    return Response(
        {"detail": "The client portal is not enabled."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class ClientLoginView(APIView):
    """POST client/auth/login/ — PUBLIC. Exchange client credentials for a client-JWT."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    # Credentials use the dedicated per-address + per-IP buckets rather than the broad
    # API throttle. DRF supplies the real Retry-After header from these classes.
    throttle_classes = AUTH_THROTTLES

    def post(self, request):
        if not getattr(settings, "ENABLE_CLIENT_PORTAL", False):
            return _portal_enabled_response()
        ser = ClientLoginRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        client = authenticate_client(ser.validated_data["email"], ser.validated_data["password"])
        if client is None:
            return Response(
                {"detail": "Invalid email or password."}, status=status.HTTP_401_UNAUTHORIZED
            )
        tokens = build_tokens_for_client(client)
        return Response(
            {"client": ClientIdentitySerializer(client).data, **tokens},
            status=status.HTTP_200_OK,
        )


class ClientTokenRefreshView(APIView):
    """POST client/auth/token/refresh/ — PUBLIC. Mint a fresh access token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not getattr(settings, "ENABLE_CLIENT_PORTAL", False):
            return _portal_enabled_response()
        ser = ClientTokenRefreshRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        import jwt

        try:
            payload = decode_client_token(ser.validated_data["refresh"])
        except jwt.PyJWTError:
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        if payload.get("token_type") != "refresh":
            return Response({"detail": "Not a refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        client = Client.objects.filter(id=payload.get("client_id"), is_active=True).first()
        if client is None or not token_matches_current_session(client, payload):
            # One generic shape for unknown/inactive/revoked session state.
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(build_tokens_for_client(client), status=status.HTTP_200_OK)


class ClientSetPasswordView(APIView):
    """POST client/auth/password/set/ — PUBLIC. Set a password from a single-use token.

    Safety net for invites that were claimed without a password. On success it mints a
    fresh client-JWT so the caller can drop the visitor straight into the workspace.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not getattr(settings, "ENABLE_CLIENT_PORTAL", False):
            return _portal_enabled_response()

        from apps.clients.serializers import PasswordSetRequestSerializer
        from apps.clients.services.set_password import (
            SetPasswordError,
            set_password_with_token,
        )

        ser = PasswordSetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            client = set_password_with_token(
                ser.validated_data["token"], ser.validated_data["password"]
            )
        except SetPasswordError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        tokens = build_tokens_for_client(client)
        return Response(
            {"client": ClientIdentitySerializer(client).data, **tokens},
            status=status.HTTP_200_OK,
        )


class ClientLogoutView(APIView):
    """POST client/auth/logout/ — CLIENT. Stateless JWT: the client just drops the token."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def post(self, request):
        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


class ClientMeView(APIView):
    """GET client/me/ — CLIENT. The authenticated client's identity."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        return Response(ClientIdentitySerializer(request.user).data)


# ── Portal data endpoints ────────────────────────────────────────────────────
class PortalWSTicketView(APIView):
    """POST portal/ws-ticket/ — CLIENT. Mint a short-lived WS-only credential."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def post(self, request):
        from apps.clients.ws_ticket import WS_TICKET_MAX_AGE_SECONDS, mint_client_ws_ticket

        return Response(
            {
                "ticket": mint_client_ws_ticket(request.user),
                "expiresIn": WS_TICKET_MAX_AGE_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class PortalOverviewView(APIView):
    """GET portal/overview/ — CLIENT. The personalized workspace payload."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        client = request.user
        lead = client.lead
        from apps.conversations.services.history import (
            get_or_create_portal_conversation,
            unread_count,
        )

        conv = get_or_create_portal_conversation(client)
        unread = unread_count(conv, client=client)

        # ── Contract mapping (frontend PortalOverview) ───────────────────────
        # The internal journey state machine (apps.journey.JourneyState) is NOT
        # the client-facing portal stage. The web workspace expects a fixed
        # PortalStage enum and PortalNextStepKey enum; emitting anything else
        # makes the workspace overview crash ("reading 'title'"). Map here.
        journey_state = (lead.journey_state if lead else "CLIENT")

        # journey_state -> PortalStage (frontend src/types/portal.types.ts)
        _STAGE_MAP = {
            "ARRIVED": "review_ready",
            "IN_REVIEW": "briefing_preparing",
            "DIAGNOSED": "review_ready",
            "CLIENT_PAGE": "review_ready",
            "INVITED": "conversation_arranging",
            "CLIENT": "conversation_arranging",
            "ENGAGED": "evaluation_in_progress",
            "DORMANT": "review_ready",
        }
        stage = _STAGE_MAP.get(journey_state, "review_ready")

        # nextSteps must be PortalNextStepKey values, not free text.
        next_steps: list[str] = ["read_briefing", "talk_to_itrix"]
        astop = getattr(lead, "astop_engagement", None) if lead is not None else None
        if astop is None:
            next_steps.append("consider_astop")
        elif astop.has_verified_value:
            next_steps.append("consider_alpha_assessment")

        payload = {
            "client": client,
            "stage": stage,
            "unreadMessages": unread,
            "briefingAvailable": True,
            "nextSteps": next_steps,
            "ndaSigned": client.nda_signed,
            "lastUpdated": conv.last_message_at,
        }
        return Response(PortalOverviewSerializer(payload).data)


class PortalBriefingView(APIView):
    """GET portal/briefing/ — a client-safe projection of the current My Review.

    The persisted ResultPage remains the source of truth. This endpoint never regenerates
    analysis and never returns tier, score, hidden persona, internal source metadata or a
    commercial pathway. Product recommendation is shown only after the deterministic
    Problem-Mirror gate permits one.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        from apps.conversations.models_thread import Thread
        from apps.conversations.services.engagement_state import recommendation_allowed
        from apps.result_page.models import ResultPage

        client = request.user
        result = ResultPage.objects.filter(lead=client.lead).first()
        if result is None or result.generation_status != ResultPage.GenerationStatus.READY:
            return Response({"detail": "Briefing is not ready."}, status=status.HTTP_404_NOT_FOUND)

        thread = (
            Thread.objects.filter(client=client).order_by("-updated_at").first()
            or Thread.objects.filter(lead=client.lead).order_by("-updated_at").first()
        )
        route = getattr(client.lead, "product_route", "general") or "general"
        if thread is not None and not recommendation_allowed(thread):
            route = "general"
        if route not in {"alpha_compute", "alpha_core", "both", "general"}:
            route = "general"

        sections: list[dict] = []
        mirror = result.problem_mirror_structured or {}
        stated = [str(v).strip() for v in (mirror.get("statedFacts") or []) if str(v).strip()]
        mirror_parts = [*stated]
        for key in ("affectedDecision", "consequence", "constraints", "evidenceGap", "successCondition"):
            value = mirror.get(key)
            if isinstance(value, str) and value.strip():
                mirror_parts.append(value.strip())
        if mirror_parts:
            sections.append({"key": "problem_mirror", "title": "Problem Mirror", "body": " ".join(mirror_parts), "updated": False})

        if result.alpha_fit_summary:
            sections.append({"key": "alpha_fit", "title": "Current fit", "body": result.alpha_fit_summary, "updated": False})

        if result.diagnosis:
            parts = []
            for row in result.diagnosis:
                if not isinstance(row, dict):
                    continue
                text = row.get("observation") or row.get("summary") or row.get("pressure")
                if text:
                    parts.append(str(text).strip())
            if parts:
                sections.append({"key": "diagnosis", "title": "Diagnosis", "body": " ".join(parts), "updated": False})

        if result.kpi_preview:
            labels = []
            for row in result.kpi_preview:
                if isinstance(row, dict):
                    label = row.get("label")
                    metric = row.get("metric")
                    if label:
                        labels.append(f"{label}: {metric}" if metric else str(label))
            if labels:
                sections.append({"key": "kpis", "title": "What to measure", "body": "; ".join(labels), "updated": False})

        return Response({
            "productRoute": route,
            # Commercial/legal pathway is intentionally absent until a separately governed
            # contract flow has an authoritative basis.
            "licensePathway": None,
            "sections": sections,
            "lastUpdated": result.generated_at,
            "updatedNotice": False,
        })


class PortalConversationListView(APIView):
    """GET portal/conversations/ — CLIENT. The client's conversation threads."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        from apps.conversations.serializers import ConversationSummarySerializer
        from apps.conversations.services.history import get_or_create_portal_conversation

        from apps.conversations.models import ConversationContext

        client = request.user
        get_or_create_portal_conversation(client)  # ensure at least one inbox thread exists
        # Messaging is client↔itriX correspondence, not the AI review history. Claimed
        # review/client-page conversations belong under "Your conversations" and must
        # never be duplicated into the inbox.
        convs = client.conversations.filter(
            is_active=True,
            context__in=[ConversationContext.PORTAL, ConversationContext.CUSTOMER_SUCCESS],
        ).order_by("-last_message_at")
        return Response(
            ConversationSummarySerializer(convs, many=True, context={"client": client}).data
        )


class PortalConversationMessagesView(APIView):
    """GET portal/conversations/{id}/messages/ — CLIENT. Deliverable messages in a thread."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request, conversation_id):
        from apps.conversations.models import Conversation, ConversationContext
        from apps.conversations.serializers import ConversationThreadSerializer
        from apps.conversations.services.history import mark_read

        from apps.conversations.services.history import ensure_portal_thread

        client = request.user
        conv = get_object_or_404(
            Conversation,
            id=conversation_id,
            client=client,
            context__in=[ConversationContext.PORTAL, ConversationContext.CUSTOMER_SUCCESS],
        )
        # Eager: a file can be attached BEFORE the first message is sent, and
        # attachments stage against the thread — so the composer needs its id now.
        ensure_portal_thread(conv, client)
        conv.refresh_from_db()
        mark_read(conv, client=client)
        return Response(ConversationThreadSerializer(conv).data)

    def post(self, request, conversation_id):
        """
        Send a client message on this conversation.

        ── THE ROUTE THE SCREEN WAS ALREADY CALLING (2026-08-10) ───────────────
        The Messages screen has always POSTed here (portalApi.sendMessage); the
        view only implemented GET, so every send died as a 405 behind the proxy's
        generic 502. The reply contract is deliberately honest: the response is
        the client's own PERSISTED message — not a fabricated agent answer. The
        team's (or agent's) reply, when it exists, arrives through the same
        polling that already refreshes the thread.

        Attachments ride the same turn: `attachmentIds` are the ids the client
        staged through the attachments endpoint against this conversation's
        thread. The link is made EXPLICITLY here (ingest.associate_attachments)
        — ingest itself only records the ids in meta, and a link that exists
        only in meta renders nothing.
        """
        from apps.conversations.models import Conversation, ConversationContext
        from apps.conversations.serializers import MessageSerializer
        from apps.conversations.services import ingest
        from apps.conversations.services.history import ensure_portal_thread

        client = request.user
        conv = get_object_or_404(
            Conversation,
            id=conversation_id,
            client=client,
            context__in=[ConversationContext.PORTAL, ConversationContext.CUSTOMER_SUCCESS],
        )

        body = (request.data.get("body") or "").strip()
        attachment_ids = request.data.get("attachmentIds") or []
        if not isinstance(attachment_ids, list):
            attachment_ids = []
        attachment_ids = [str(a) for a in attachment_ids][:8]
        if not body and not attachment_ids:
            return Response({"detail": "A message is required."}, status=status.HTTP_400_BAD_REQUEST)

        thread = ensure_portal_thread(conv, client)
        try:
            message = ingest.ingest_inbound(
                conv,
                sender_kind="client",
                body=body,
                client=client,
                thread=thread,
                meta={"attachment_ids": attachment_ids},
            )
        except Exception as exc:  # noqa: BLE001 — MessageTooLong carries its own text
            return Response({"detail": str(exc)}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        if attachment_ids:
            ingest.associate_attachments(message, attachment_ids)

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class PortalDocumentsView(APIView):
    """GET portal/documents/ — CLIENT. Authorization-aware data room.

    An NDA is displayed as protection state, never as the permission itself. Restricted
    documents unlock only when this client has an active explicit ContentAuthorization
    and any required agreement prerequisite is also satisfied.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        from django.db.models import Q
        from django.utils import timezone

        from apps.knowledge_core.models import ContentAuthorization, KnowledgeDocument

        client = request.user
        now = timezone.now()
        authorized_ids = set(
            ContentAuthorization.objects.filter(
                subject_kind=ContentAuthorization.SubjectKind.CLIENT,
                subject_id=str(client.id),
                active=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("document_id", flat=True)
        )

        docs = list(
            KnowledgeDocument.objects.filter(is_current=True)
            .exclude(disclosure_level__in=["internal_only", "prohibited", "customer_contract"])
            .order_by("namespace", "title")
        )
        open_docs = []
        restricted_docs = []
        for doc in docs:
            level = doc.disclosure_level
            row = {
                "title": doc.title,
                "disclosure": level,
                "href": "",
                "locked": False,
            }
            if level in {"public", "controlled_public"}:
                open_docs.append(row)
                continue
            explicitly_authorized = doc.id in authorized_ids
            agreement_ok = level != "nda_only" or bool(client.nda_signed)
            row["locked"] = not (explicitly_authorized and agreement_ok)
            restricted_docs.append(row)

        open_folders = [{"folder": "Available materials", "documents": open_docs}]
        data_room_folders = [{"folder": "Authorized materials", "documents": restricted_docs}]
        # This is the only client-plane data-room unlock bit. It is derived from
        # explicit per-document authorization (plus any agreement prerequisite),
        # never from account, email-verification, journey or NDA state alone.
        data_room_authorized = any(not row["locked"] for row in restricted_docs)
        lead = client.lead
        nda = getattr(lead, "nda", None) if lead is not None else None
        nda_problem = (getattr(nda, "problem_context", "") or getattr(lead, "compute_bottleneck", "") or "").strip()
        nda_workload = (getattr(nda, "workload_context", "") or getattr(lead, "workload_type", "") or "").strip()
        return Response(
            PortalDataRoomSerializer(
                {
                    "ndaSigned": bool(client.nda_signed),
                    "dataRoomAuthorized": data_room_authorized,
                    "openFolders": open_folders,
                    "dataRoomFolders": data_room_folders,
                    "ndaContextPresent": bool(nda_problem or nda_workload),
                    "ndaProblemContext": nda_problem,
                    "ndaWorkloadContext": nda_workload,
                    "ndaDesiredOutcome": (getattr(nda, "desired_outcome", "") or "").strip(),
                    "ndaDiscussionReason": (getattr(nda, "discussion_reason", "") or "").strip(),
                }
            ).data
        )


class PortalEvaluationView(APIView):
    """GET portal/evaluation/ — CLIENT. Client-visible evaluation status."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        lead = request.user.lead
        evaluation = None
        astop = None
        if lead is not None:
            evaluation = lead.evaluations.order_by("-created_at").first()
            astop = getattr(lead, "astop_engagement", None)
        if evaluation is not None:
            return Response(
                PortalEvaluationSerializer(
                    {
                        "exists": True,
                        "kind": "alpha_compute",
                        "stage": evaluation.status,
                        "kpis": evaluation.kpis or [],
                        "reportHref": "",
                        # Only final/customer-facing fee state crosses this boundary.
                        "customerFeeStatus": evaluation.customer_fee_status,
                        "finalAssessmentFee": evaluation.final_assessment_fee if evaluation.fee_finalized_at else None,
                    }
                ).data
            )
        if astop is not None:
            return Response(
                PortalEvaluationSerializer(
                    {
                        "exists": True,
                        "kind": "astop",
                        "stage": astop.stage,
                        "astopStage": astop.stage,
                        "kpis": [],
                        "reportHref": "",
                        "ttfvSeconds": astop.ttfv_seconds,
                        "verifiedValue": astop.verified_value or {},
                    }
                ).data
            )
        return Response(PortalEvaluationSerializer({"exists": False, "kind": "astop", "stage": "", "kpis": [], "reportHref": ""}).data)


class PortalPoCView(APIView):
    """GET portal/poc/ — CLIENT. Client-visible PoC status."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        lead = request.user.lead
        poc = None
        if lead is not None:
            poc = lead.pocs.order_by("-created_at").first()
        if poc is None:
            return Response(PortalPoCSerializer({"exists": False, "stage": "", "milestones": [], "successCriteria": []}).data)
        return Response(
            PortalPoCSerializer(
                {
                    "exists": True,
                    "stage": poc.status,
                    "milestones": poc.milestones or [],
                    "successCriteria": poc.kpis or [],
                }
            ).data
        )


# Every switch defaults ON: a customer who never opened Settings still gets told
# about the things the portal exists to tell them about. An empty stored dict
# therefore means "never touched", not "everything off".
NOTIFICATION_DEFAULTS = {
    "newTeamMessage": True,
    "reviewUpdated": True,
    "evalOrPocStatus": True,
    "documentShared": True,
}


def _settings_payload(client):
    """The nested PortalSettings shape the Settings screen renders."""
    team = [{"email": client.email, "status": "active"}]
    team += [
        {"email": invite.email, "status": "invited"}
        for invite in client.team_invites.filter(status="invited").order_by("created_at")
    ]
    notifications = {**NOTIFICATION_DEFAULTS, **(client.notification_prefs or {})}
    return {
        "profile": {
            "fullName": client.full_name or None,
            "email": client.email,
            "organization": client.organization or None,
            "role": client.role or None,
        },
        "team": team,
        "notifications": notifications,
    }


class PortalSettingsView(APIView):
    """GET/PATCH portal/settings/ — CLIENT. Profile · team access · notifications."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        return Response(_settings_payload(request.user))

    def patch(self, request):
        client = request.user
        ser = PortalSettingsPatchSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        profile = data.get("profile") or {}
        update_fields = []
        for camel, attr in (("fullName", "full_name"), ("organization", "organization"), ("role", "role")):
            if camel in profile and profile[camel] is not None:
                setattr(client, attr, profile[camel])
                update_fields.append(attr)

        if "notifications" in data:
            merged = {**NOTIFICATION_DEFAULTS, **(client.notification_prefs or {}), **data["notifications"]}
            client.notification_prefs = merged
            update_fields.append("notification_prefs")

        if update_fields:
            client.save(update_fields=[*update_fields, "updated_at"])
        return Response(_settings_payload(client))


class PortalNdaRequestView(APIView):
    """
    POST portal/nda/request/ — CLIENT. Ask for an NDA from the Documents screen.

    ── WHY THIS EXISTS (change request, 2026-08-10) ─────────────────────────────
    The Documents screen's "Arrange an NDA" control was a LINK into Messages, so
    pressing it navigated the customer away from the room they were trying to
    open and left them to compose the request themselves. It now submits here,
    in place.

    THREE THINGS HAPPEN, and the confirmation the customer reads promises exactly
    these and nothing more:
      1. the request is stamped on the Client (`nda_requested_at`) — a request,
         never `nda_signed`, which is the countersigned fact and would open the
         data room on the strength of a button press;
      2. a message is posted into their portal conversation, so "keep an eye on
         your workspace inbox" is true rather than a hopeful phrase;
      3. the team is alerted by email and the customer gets a confirmation to the
         address on their account.

    Idempotent by intent: asking twice keeps the FIRST timestamp and does not
    spam the team, because a customer who presses a button twice has not made two
    requests.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    # The message the customer sees in their inbox, and the sentence the screen
    # shows. One string, so the two can never drift apart.
    INBOX_BODY = (
        "Thank you — we have your request for an NDA. The itriX team will prepare it "
        "and send it to the address on your account for signature. You will see it "
        "here in your inbox as well, so you can keep an eye on either. Signing the NDA "
        "protects later confidential exchange; access to restricted material is granted "
        "separately when that specific material is authorized."
    )

    def post(self, request):
        from django.utils import timezone

        from apps.conversations.services import ingest
        from apps.conversations.services.history import (
            ensure_portal_thread,
            get_or_create_portal_conversation,
        )

        client = request.user

        if client.nda_signed:
            return Response(
                {"detail": "Your NDA is already in place.", "ndaRequested": True},
                status=status.HTTP_200_OK,
            )

        # A request for agreement protection needs a non-confidential problem/workload
        # context. Reuse what the relationship already knows rather than asking twice.
        lead = client.lead
        from apps.nda.services.nda_creator import create_nda_for_lead

        nda = create_nda_for_lead(lead)
        problem = str(request.data.get("problemContext") or nda.problem_context or lead.compute_bottleneck or "").strip()
        workload = str(request.data.get("workloadContext") or nda.workload_context or lead.workload_type or "").strip()
        desired = str(request.data.get("desiredOutcome") or nda.desired_outcome or "").strip()
        reason = str(request.data.get("discussionReason") or nda.discussion_reason or "").strip()
        if not (problem or workload):
            return Response(
                {
                    "detail": "Please tell us what problem or workload you would like to discuss under this NDA.",
                    "code": "nda_context_required",
                    "contextRequired": True,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        nda.problem_context = problem
        nda.workload_context = workload
        nda.desired_outcome = desired
        nda.discussion_reason = reason
        nda.save(update_fields=["problem_context", "workload_context", "desired_outcome", "discussion_reason", "updated_at"])

        already_requested = client.nda_requested_at is not None
        if not already_requested:
            client.nda_requested_at = timezone.now()
            client.save(update_fields=["nda_requested_at", "updated_at"])

        # The inbox note. Best-effort: the request is already recorded, and losing
        # the customer's stamped request because a message failed to persist would
        # be the worse outcome of the two.
        if not already_requested:
            try:
                conv = get_or_create_portal_conversation(client)
                thread = ensure_portal_thread(conv, client)
                ingest.ingest_agent_message(
                    conv, agent_key="concierge", body=self.INBOX_BODY, thread=thread
                )
            except Exception:  # noqa: BLE001
                logger.exception("nda.request inbox note failed for client %s", client.id)

            try:
                self._notify(client)
            except Exception:  # noqa: BLE001
                logger.exception("nda.request notification failed for client %s", client.id)

        logger.info("clients.nda_requested client=%s repeat=%s", client.id, already_requested)
        return Response(
            {"ndaRequested": True, "message": self.INBOX_BODY},
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _notify(client):
        from apps.emails.services.email_sender import send_email

        internal_to = getattr(settings, "INTERNAL_ALERT_EMAIL", "") or ""
        if internal_to:
            send_email(
                kind="internal_alert",
                to_email=internal_to,
                subject=f"NDA requested — {client.organization or client.email}",
                body=(
                    f"{client.full_name or client.email} requested an NDA from the "
                    f"Documents screen.\n\n"
                    f"Client: {client.id}\n"
                    f"Email: {client.email}\n"
                    f"Organisation: {client.organization or '(not given)'}\n"
                    f"Problem/workload: {(getattr(getattr(client.lead, 'nda', None), 'problem_context', '') or getattr(client.lead, 'workload_type', ''))[:500]}\n"
                ),
                lead=getattr(client, "lead", None),
            )
        send_email(
            kind="confirmation",
            to_email=client.email,
            subject="Your itriX NDA is being prepared",
            body=(
                f"{PortalNdaRequestView.INBOX_BODY}\n\n"
                "You do not need to do anything until it arrives."
            ),
            lead=getattr(client, "lead", None),
        )


class PortalTeamInviteView(APIView):
    """
    POST portal/settings/team/invite/ — CLIENT. Record a teammate invitation.

    The Settings screen has always rendered this form; the route simply did not
    exist, so pressing Invite failed. The row is the durable record and shows as
    'invited' in the team list (see ClientTeamInvite for what activation still
    requires). Inviting the same address twice is a no-op, not an error.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def post(self, request):
        from apps.clients.models import ClientTeamInvite

        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        client = request.user
        email = (request.data.get("email") or "").strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            return Response({"detail": "A valid email is required."}, status=status.HTTP_400_BAD_REQUEST)
        if email == client.email.lower():
            return Response(
                {"detail": "That address is already on this workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Sending the email is part of the invitation, not an optional side effect.
        # Previously we wrote the row and returned 201 without attempting delivery, so
        # Settings displayed "invited" for an address that had received nothing.
        from apps.emails.models import EmailLog
        from apps.emails.services.team_invite_builder import build_team_invite_email

        mail = build_team_invite_email(client, invite_email=email)
        delivery_enabled = bool(getattr(settings, "ENABLE_EMAIL_DELIVERY", False))
        if delivery_enabled and mail.status != EmailLog.Status.SENT:
            logger.error(
                "portal.team_invite delivery failed client=%s mail_log=%s",
                client.id,
                mail.id,
            )
            return Response(
                {"detail": "We could not send that invitation. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        ClientTeamInvite.objects.get_or_create(client=client, email=email)
        return Response(_settings_payload(client), status=status.HTTP_201_CREATED)


def _visitor_session_from(request) -> str:
    """
    Read the signed visitor-session id from the request.

    Checked in header-then-cookie order so a server-side proxy can forward it explicitly
    without depending on cookie passthrough. Returns "" when absent — a visitor who
    never had a session simply has no threads to claim, which is not an error.
    """
    header = request.META.get("HTTP_X_ITRIX_SESSION", "") or ""
    if header.strip():
        return header.strip()[:64]
    cookie = request.COOKIES.get("itrix_visitor_session", "") or ""
    return cookie.strip()[:64]


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 3: the portal's next-best-action
# ─────────────────────────────────────────────────────────────────────────────
class PortalNextBestActionView(APIView):
    """
    GET portal/next-action/ — CLIENT plane.

    PASSES THROUGH ``nba_precedence`` (§11.1), the SAME rule the cockpit uses, so a
    customer and an operator can never see contradictory guidance.

    The customer receives ONLY the action. The suppression reason is internal — a
    customer does not need to be told we decided not to sell to them today, and telling
    them would surface a commercial deliberation they never asked to be part of.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        from apps.governance.services import nba_precedence

        client = request.user
        candidates = self._candidates(client)
        decision = nba_precedence.next_best_action(client, candidates)

        return Response(
            {
                # to_client_payload() deliberately omits suppressionReason.
                "nextBestAction": decision.to_client_payload(),
                "cards": self._cards(client),
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _candidates(client):
        try:
            from apps.agents.services.strategy import nba_candidates

            return nba_candidates(getattr(client, "lead", None))
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _cards(client):
        """Inline cards, with the commitment gate already applied at the payload."""
        try:
            from apps.journey.services import cards

            return cards.build(getattr(client, "lead", None), client=client)
        except Exception:  # noqa: BLE001
            return []
