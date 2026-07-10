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
    PortalOverviewSerializer,
    PortalPoCSerializer,
    PortalSettingsSerializer,
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

        next_steps: list[str] = []
        if not client.nda_signed:
            next_steps.append("Review and sign the NDA to unlock detailed technical materials.")
        next_steps.append("Continue the conversation with your iTrix contact in the portal.")

        payload = {
            "client": client,
            "stage": (lead.journey_state if lead else "CLIENT"),
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

        client = request.user
        get_or_create_portal_conversation(client)  # ensure at least one exists
        convs = client.conversations.filter(is_active=True).order_by("-last_message_at")
        return Response(
            ConversationSummarySerializer(convs, many=True, context={"client": client}).data
        )


class PortalConversationMessagesView(APIView):
    """GET portal/conversations/{id}/messages/ — CLIENT. Deliverable messages in a thread."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request, conversation_id):
        from apps.conversations.models import Conversation
        from apps.conversations.serializers import ConversationThreadSerializer
        from apps.conversations.services.history import mark_read

        client = request.user
        conv = get_object_or_404(Conversation, id=conversation_id, client=client)
        mark_read(conv, client=client)
        return Response(ConversationThreadSerializer(conv).data)


class PortalDocumentsView(APIView):
    """GET portal/documents/ — CLIENT. NDA-aware data room."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        client = request.user
        nda = client.nda_signed
        # Public materials are always available; NDA-only materials unlock post-signature.
        documents = [
            {"title": "iTrix overview", "disclosure": "public", "href": "", "locked": False},
            {"title": "ALPHA approach summary", "disclosure": "controlled_public", "href": "", "locked": False},
            {"title": "Technical deep-dive", "disclosure": "nda_only", "href": "", "locked": not nda},
            {"title": "Evaluation methodology", "disclosure": "nda_only", "href": "", "locked": not nda},
        ]
        return Response(PortalDataRoomSerializer({"ndaSigned": nda, "documents": documents}).data)


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


class PortalSettingsView(APIView):
    """GET/PATCH portal/settings/ — CLIENT. Client profile."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def get(self, request):
        return Response(PortalSettingsSerializer(request.user).data)

    def patch(self, request):
        client = request.user
        ser = PortalSettingsSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        for field_attr, value in (
            ("full_name", data.get("full_name")),
            ("organization", data.get("organization")),
            ("role", data.get("role")),
        ):
            if value is not None:
                setattr(client, field_attr, value)
        client.save(update_fields=["full_name", "organization", "role", "updated_at"])
        return Response(PortalSettingsSerializer(client).data)
