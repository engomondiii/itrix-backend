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
from apps.clients.tokens import build_tokens_for_client, decode_client_token  # noqa: E402


def _portal_enabled_response():
    return Response(
        {"detail": "The client portal is not enabled."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class ClientLoginView(APIView):
    """POST client/auth/login/ — PUBLIC. Exchange client credentials for a client-JWT."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

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
        if client is None:
            return Response({"detail": "Client not found."}, status=status.HTTP_401_UNAUTHORIZED)
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
        if client.nda_signed:
            next_steps.append("consider_evaluation")

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
    """GET portal/documents/ — CLIENT. NDA-aware data room."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        client = request.user
        nda = client.nda_signed
        # Public materials are always available; NDA-only materials unlock post-signature.
        # Grouped into the folder shape the Documents screen renders (see the
        # serializer's SHAPE FIX note): open folders always show, data-room folders
        # carry the locked flag until the NDA is signed.
        open_folders = [
            {
                "folder": "Overview",
                "documents": [
                    {"title": "itriX overview", "disclosure": "public", "href": "", "locked": False},
                    {"title": "ALPHA approach summary", "disclosure": "controlled_public", "href": "", "locked": False},
                ],
            }
        ]
        data_room_folders = [
            {
                "folder": "Technical materials",
                "documents": [
                    {"title": "Technical deep-dive", "disclosure": "nda_only", "href": "", "locked": not nda},
                    {"title": "Evaluation methodology", "disclosure": "nda_only", "href": "", "locked": not nda},
                ],
            }
        ]
        return Response(
            PortalDataRoomSerializer(
                {"ndaSigned": nda, "openFolders": open_folders, "dataRoomFolders": data_room_folders}
            ).data
        )


class PortalEvaluationView(APIView):
    """GET portal/evaluation/ — CLIENT. Client-visible evaluation status."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        lead = request.user.lead
        evaluation = None
        if lead is not None:
            evaluation = lead.evaluations.order_by("-created_at").first()
        if evaluation is None:
            return Response(PortalEvaluationSerializer({"exists": False, "stage": "", "kpis": [], "reportHref": ""}).data)
        return Response(
            PortalEvaluationSerializer(
                {
                    "exists": True,
                    "stage": evaluation.status,
                    "kpis": evaluation.kpis or [],
                    "reportHref": "",
                }
            ).data
        )


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
        "here in your inbox as well, so you can keep an eye on either. Once it is "
        "signed and countersigned, your confidential data room opens automatically."
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
                "portal.team_invite delivery failed client=%s email=%s log=%s error=%s",
                client.id,
                email,
                mail.id,
                mail.error,
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
