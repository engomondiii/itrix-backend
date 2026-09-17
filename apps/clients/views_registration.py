"""Open-registration view with explicit legal-version race handling."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response

from apps.clients.serializers_auth import RegisterRequestSerializer
from apps.clients.views_auth import ACCEPTED_BODY, _PublicAuthView, _ip, _user_agent, _visitor_session

logger = logging.getLogger("itrix")


class RegisterView(_PublicAuthView):
    """POST auth/register/ — neutral open signup with enumeration-safe outcomes."""

    def post(self, request):
        from apps.clients.services import registration as registration_svc

        if not registration_svc.enabled():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = RegisterRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            registration_svc.register_client(
                email=data["email"],
                password=data["password"],
                full_name=data.get("full_name", ""),
                organization=data.get("organization", ""),
                role=data.get("role", ""),
                assent_versions=data.get("assent") or [],
                visitor_session=_visitor_session(request),
                ip=_ip(request),
                user_agent=_user_agent(request),
            )
        except registration_svc.RegistrationLegalTermsChanged:
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
        except registration_svc.RegistrationError as exc:
            # All address-dependent/non-public outcomes remain collapsed to the same 202.
            logger.warning("clients.registration_refused reason=%s", exc)
        except Exception:  # noqa: BLE001
            logger.exception("clients.registration_failed")
            return Response(
                {"detail": "Registration service unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(ACCEPTED_BODY, status=status.HTTP_202_ACCEPTED)
