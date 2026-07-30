"""
THE AUTHENTICATION SURFACE (Backend v7.2 §15.1).

    POST  auth/register/                 open registration. 404 when the kill switch is thrown
    POST  auth/password-reset/request/   always the same answer
    POST  auth/password-reset/confirm/   single-use token; burn precedes write
    GET   auth/invite/lookup/?code=      one failure shape for three causes
    POST  auth/verify-email/confirm/     single-use token; burn precedes the flag write
    POST  auth/verify-email/resend/      always the same answer
    POST  client/auth/password/          authenticated change; invalidates other sessions

── WHY THIS IS A SEPARATE MODULE FROM views.py ─────────────────────────────
v7.2 §14 recorded that the shipped file is `views.py` and is NOT renamed. It is not: this
is a sibling. Seven unauthenticated routes that share one hard property — they answer the
same way whether or not an account exists — are easier to keep correct in one file where
that property is stated once, than scattered through 400 lines of portal data endpoints
where the next person to add a view will not see it.

── THE ONE RULE THAT GOVERNS EVERY VIEW BELOW ──────────────────────────────
An unauthenticated endpoint answers the same way whether or not the account exists. Where
that means discarding what the service learned, the discarding is explicit and commented,
because it looks like a bug to anybody who has not read this line.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clients.backends import ClientJWTAuthentication
from apps.clients.permissions import IsAuthenticatedClient
from apps.clients.serializers_auth import (
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterRequestSerializer,
    VerifyEmailConfirmSerializer,
    VerifyEmailResendSerializer,
)
from apps.clients.throttles import AUTH_THROTTLES

logger = logging.getLogger("itrix")

# ONE body, ONE status. Module-level so no branch can vary it by accident.
ACCEPTED_BODY = {"accepted": True}


def _ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:300]


class _PublicAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = AUTH_THROTTLES


class RegisterView(_PublicAuthView):
    """
    POST auth/register/ — anyone may open a workspace (R60).

    ── 202 WITH AN IDENTICAL BODY, WHATEVER HAPPENED (R64) ─────────────────
    Created, already-in-use, or refused for a reason we will not describe: one answer. When
    the address is already held, the registration service emails the person who OWNS it; the
    person who typed it learns nothing (§27.6).

    ── AND 404 WHEN THE KILL SWITCH IS THROWN, NOT 403 ─────────────────────
    A disabled capability does not advertise itself. `ENABLE_OPEN_SIGNUP` defaults TRUE and
    is a kill switch rather than a product gate (§27.10).
    """

    def post(self, request):
        from apps.clients.services import registration as registration_svc

        if not registration_svc.enabled():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = RegisterRequestSerializer(data=request.data)
        # A 400 here is a malformed request or a missing assent array — our own programming
        # error, and not usable to probe for addresses. Everything a person could FIX has
        # already been validated on the surface.
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
        except registration_svc.RegistrationError as exc:
            # Logged, not returned. The outcome is still an acceptance, because any other
            # answer is a fact about the address.
            logger.warning("clients.registration_refused reason=%s", exc)
        except Exception:  # noqa: BLE001
            logger.exception("clients.registration_failed")
            return Response(
                {"detail": "Registration service unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(ACCEPTED_BODY, status=status.HTTP_202_ACCEPTED)


class PasswordResetRequestView(_PublicAuthView):
    """
    POST auth/password-reset/request/ — one answer, always.

    The service returns None in every case for the same reason this returns one body: a
    caller that could branch on the outcome would be one edit away from reporting it.
    """

    def post(self, request):
        from apps.clients.services import password_reset as reset_svc

        ser = PasswordResetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            reset_svc.request_reset(ser.validated_data["email"], ip=_ip(request))
        except Exception:  # noqa: BLE001
            # Swallowed on purpose. A backend failure must not be distinguishable from an
            # address that has no workspace.
            logger.exception("clients.reset_request_failed")
        return Response(ACCEPTED_BODY, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(_PublicAuthView):
    """
    POST auth/password-reset/confirm/ — reports failure honestly.

    Unlike the request, this one must: the visitor is holding a link they believe works, and
    telling them nothing leaves them stuck. It still does not distinguish expired from
    consumed from unknown.
    """

    def post(self, request):
        from apps.clients.services import password_reset as reset_svc

        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            reset_svc.confirm_reset(ser.validated_data["token"], ser.validated_data["password"])
        except reset_svc.ResetError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_410_GONE)
        return Response(
            {
                "reset": True,
                # Named so the surface can tell the user. Silent invalidation looks like a
                # fault; stated invalidation is a security feature they can watch work.
                "otherSessionsSignedOut": True,
            },
            status=status.HTTP_200_OK,
        )


class InviteLookupView(_PublicAuthView):
    """
    GET auth/invite/lookup/?code= — usable-or-not, and where to go. Nothing else.

    ── EVERYTHING IT RETURNS IS A DISCLOSURE TO AN UNAUTHENTICATED PARTY ───
    So it returns two fields. No Lead, no organisation, no persona, no journey state, no
    email, and no hint of which of the three failure causes applied. A helpful
    "Welcome back, {organisation}" here would be a free customer list (§15.4).
    """

    def get(self, request):
        from apps.clients.services.invite import lookup_invite

        code = (request.query_params.get("code") or "").strip()
        usable, redeem_url = lookup_invite(code)
        body = {"usable": usable}
        if usable and redeem_url:
            body["redeemUrl"] = redeem_url
        # 200 in every case. A status code is as readable as a body.
        return Response(body, status=status.HTTP_200_OK)


class VerifyEmailConfirmView(_PublicAuthView):
    """POST auth/verify-email/confirm/ — burn, then write the flag. One error for all causes."""

    def post(self, request):
        from apps.clients.services import verification as verification_svc

        ser = VerifyEmailConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            verification_svc.confirm(ser.validated_data["token"])
        except verification_svc.VerificationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_410_GONE)
        return Response({"confirmed": True}, status=status.HTTP_200_OK)


class VerifyEmailResendView(APIView):
    """
    POST auth/verify-email/resend/ — one answer, always.

    Unknown, unconfirmed, already confirmed, or the mail service down: 202 with one body. A
    resend that answered differently would be a free enumeration oracle, and a particularly
    quiet one, because nobody thinks of a resend button as an authentication endpoint.

    Accepts an authenticated client (who need not name an address) or an anonymous caller
    (who must).
    """

    # AllowAny with the client authentication class attached: an authenticated client need
    # not name an address, and an anonymous caller may. The auth class returns None when
    # there are no credentials, so both reach the same handler.
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = AUTH_THROTTLES

    def post(self, request):
        from apps.clients.services import verification as verification_svc

        ser = VerifyEmailResendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        address = (ser.validated_data.get("email") or "").strip()
        client = getattr(request, "user", None)
        if not address and getattr(client, "email", None):
            address = client.email

        try:
            verification_svc.resend(address, ip=_ip(request))
        except Exception:  # noqa: BLE001
            logger.exception("clients.verification_resend_failed")
        return Response(ACCEPTED_BODY, status=status.HTTP_202_ACCEPTED)


class ClientPasswordChangeView(APIView):
    """
    POST client/auth/password/ — the authenticated change.

    Requires the current password. Not because the JWT is insufficient, but because a stolen
    session should not be enough to lock the owner out of their own workspace.
    """

    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]
    throttle_classes = AUTH_THROTTLES

    def post(self, request):
        from apps.clients.services import password_reset as reset_svc

        ser = PasswordChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        client = request.user
        credential = getattr(client, "credential", None)
        if credential is None or not credential.check_password(ser.validated_data["current_password"]):
            # One message, as on sign-in.
            return Response(
                {"detail": "Those details did not match."}, status=status.HTTP_401_UNAUTHORIZED
            )
        reset_svc.change_password(client, ser.validated_data["new_password"])
        return Response(
            {"changed": True, "otherSessionsSignedOut": True}, status=status.HTTP_200_OK
        )


def _visitor_session(request) -> str:
    """
    The anonymous session id, so registration can claim the visitor's threads (R65).

    It DELEGATES to the shipped reader in `views.py` rather than re-deriving the header and
    cookie names. Two readers that disagree by one string would mean registration silently
    claiming nothing, and the visitor losing the conversation they came to have — which is
    the one thing v2.6 promises will never happen.
    """
    from apps.clients.views import _visitor_session_from

    return _visitor_session_from(request)
