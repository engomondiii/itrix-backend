"""
Authentication serializers.

The dashboard contract (``itrix-dashboard/src/types/auth.ts``) is:

    LoginRequest  = { email, password }
    LoginResponse = { user: SessionUser, ok: true }   # tokens set as cookie by Next proxy
    SessionUser   = { id, name, email, role, avatarUrl? }

The Next ``api/auth/login`` proxy reads ``data.access`` (the JWT) and ``data.user`` from
*this* backend's response, stores ``access`` in an httpOnly cookie, and forwards
``{ user, ok }`` to the browser. So our login response must include **both**
``access``/``refresh`` and a ``user`` object.

``SessionUser.role`` is rendered as a friendly label, so we expose ``team_role`` there
as ``role`` while ``permission_role`` carries the ADMIN/ASSESSMENT/SPECIALIST/VIEWER
value for any client that wants it.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.core.exceptions import InvalidCredentials

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """The ``SessionUser`` shape the frontends consume (camelCase ``avatarUrl``)."""

    role = serializers.CharField(source="team_role", read_only=True)
    permissionRole = serializers.CharField(source="role", read_only=True)
    avatarUrl = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "email",
            "role",
            "permissionRole",
            "avatarUrl",
            "is_active",
        ]
        read_only_fields = fields

    def get_avatarUrl(self, obj) -> str | None:
        return obj.avatar_url or None


class ITrixTokenObtainPairSerializer(TokenObtainPairSerializer):
    """SimpleJWT serializer that also embeds itriX claims (used by token/refresh path)."""

    username_field = User.USERNAME_FIELD  # 'email'

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["name"] = user.display_name
        token["role"] = user.role
        token["team_role"] = user.team_role
        return token


class LoginSerializer(serializers.Serializer):
    """Validate the shape of ``{email, password}``.

    Credential verification is performed in the view (so a bad login returns a true
    401, not a 400). This serializer only guarantees the fields are present/typed.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def authenticate_user(self, request):
        """Resolve the user or raise ``InvalidCredentials`` (401)."""
        email = self.validated_data["email"].strip().lower()
        password = self.validated_data["password"]
        user = authenticate(request=request, username=email, password=password)
        if user is None:
            raise InvalidCredentials("Invalid email or password.")
        if not user.is_active:
            raise InvalidCredentials("This account is inactive.")
        return user


class MeSerializer(UserSerializer):
    """Identical to ``UserSerializer``; named for clarity at the ``/auth/me/`` view."""


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile edit (``PATCH /auth/profile/``).

    The dashboard's ``ProfileUpdate`` is ``{ name? }`` (see
    ``itrix-dashboard/src/types/settings.ts``); ``avatarUrl`` is accepted too so the
    same screen can set an avatar. Role/email are NOT editable here — role changes go
    through the admin-gated team endpoint, and email is the login identity.
    """

    avatarUrl = serializers.URLField(
        source="avatar_url", required=False, allow_blank=True
    )

    class Meta:
        model = User
        fields = ["name", "avatarUrl"]
