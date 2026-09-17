"""Invite-claim view with transactional legal-version integrity."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.serializers import ClientIdentitySerializer, InviteClaimRequestSerializer
from apps.clients.services.invite import InviteError
from apps.clients.services.invite_versioned import (
    InviteLegalTermsChanged,
    claim_invite_with_version_integrity,
)
from apps.clients.tokens import build_tokens_for_client
from apps.clients.views import _visitor_session_from
from apps.clients.views_auth import _ip, _user_agent


class InviteClaimView(APIView):
    """POST accounts/invite/{token}/claim/ — PUBLIC; the single-use token is the credential."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, token: str):
        ser = InviteClaimRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            client, requires_password_set = claim_invite_with_version_integrity(
                token,
                email=data.get("email") or None,
                password=data.get("password") or None,
                full_name=data.get("full_name", ""),
                organization=data.get("organization", ""),
                role=data.get("role", ""),
                visitor_session=_visitor_session_from(request),
                assent_versions=data.get("assent") or [],
                assent_ip=_ip(request),
                assent_user_agent=_user_agent(request),
            )
        except InviteLegalTermsChanged:
            request_id = str(getattr(request, "correlation_id", "") or "")
            body = {
                "detail": (
                    "The legal terms changed while you were reviewing them. "
                    "Please review the latest version before continuing."
                ),
                "code": "LEGAL_TERMS_CHANGED",
            }
            if request_id:
                body["requestId"] = request_id
            return Response(body, status=status.HTTP_409_CONFLICT)
        except InviteError as exc:
            # Keep the existing indistinguishable invite failure shape.
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        tokens = build_tokens_for_client(client)
        body = {
            "client": ClientIdentitySerializer(client).data,
            "requiresPasswordSet": requires_password_set,
            **tokens,
        }
        if requires_password_set:
            from apps.clients.services.set_password import issue_set_password_token

            body["setPasswordToken"] = issue_set_password_token(client)
        return Response(body, status=status.HTTP_201_CREATED)
