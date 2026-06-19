"""
Authentication views.

Endpoints (mounted at /api/v1/auth/):

    POST  login/           {email, password}  -> {access, refresh, user}
    POST  logout/          {refresh}          -> 205 (blacklists the refresh token)
    GET   me/                                 -> {user}        (Bearer required)
    POST  token/refresh/   {refresh}          -> {access, refresh?}

The dashboard's Next ``api/auth/login`` proxy reads ``access`` + ``user`` from the
login response, stores ``access`` in an httpOnly cookie, and forwards ``{user, ok}``
to the browser. ``api/auth/me`` proxies the Bearer token here and returns ``{user}``.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.authentication.permissions import IsAuthenticatedTeamMember
from apps.authentication.serializers import (
    LoginSerializer,
    ProfileUpdateSerializer,
    UserSerializer,
)
from apps.authentication.tokens import build_tokens_for_user

logger = logging.getLogger("itrix")


class LoginView(APIView):
    """Authenticate a team member and return JWT tokens + the user payload."""

    permission_classes = [AllowAny]
    authentication_classes = []  # login must not require an existing token

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.authenticate_user(request)

        tokens = build_tokens_for_user(user)
        logger.info("Login succeeded for %s (%s)", user.email, user.role)
        return Response(
            {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """Blacklist the supplied refresh token (best-effort idempotent logout)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except TokenError:
                # Already expired/blacklisted/invalid — logout is still a success.
                pass
            except Exception:  # noqa: BLE001
                logger.exception("Unexpected error blacklisting refresh token")
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """Return the currently authenticated team member."""

    permission_classes = [IsAuthenticatedTeamMember]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})


class ProfileView(APIView):
    """Self-service profile for the current team member (``/auth/profile/``).

    The dashboard's ``settings/profile`` proxy reads/writes the bare ``SessionUser``
    shape here (not wrapped in ``{user}`` like ``/auth/me/``).

        GET    profile/                 -> SessionUser
        PATCH  profile/   {name?, avatarUrl?}  -> updated SessionUser
    """

    permission_classes = [IsAuthenticatedTeamMember]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            instance=request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ITrixTokenRefreshView(TokenRefreshView):
    """Standard SimpleJWT refresh; inherits rotation/blacklist settings."""

    permission_classes = [AllowAny]
    authentication_classes = []
