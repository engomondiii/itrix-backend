"""Client logout endpoint with durable server-side revocation."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.backends import ClientJWTAuthentication
from apps.clients.permissions import IsAuthenticatedClient
from apps.clients.services.session_invalidation import revoke_current_session

logger = logging.getLogger("itrix")


class ClientLogoutView(APIView):
    """POST client/auth/logout/ — revoke the authenticated client token generation."""

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]

    def post(self, request):
        request_id = str(getattr(request, "correlation_id", "") or "")
        try:
            revoke_current_session(request.user)
        except Exception:  # noqa: BLE001 - operational failure must not masquerade as revocation
            logger.exception("clients.logout revocation_failed request_id=%s", request_id or "unknown")
            body = {
                "detail": "Session revocation is temporarily unavailable.",
                "code": "SESSION_REVOCATION_UNAVAILABLE",
            }
            if request_id:
                body["requestId"] = request_id
            return Response(body, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        body = {"detail": "Logged out.", "revoked": True}
        if request_id:
            body["requestId"] = request_id
        return Response(body, status=status.HTTP_200_OK)
