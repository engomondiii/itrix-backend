"""
Client-plane permissions.

``IsAuthenticatedClient`` passes only when the request was authenticated by
``ClientJWTAuthentication`` (i.e. ``request.user`` is a ``Client``). Team users and
anonymous requests are rejected — the client plane is separate from the team plane.

``HasSignedNDA`` additionally requires the client's NDA to be in place, gating the
data-room / NDA-only surfaces (used by the Phase 2 portal endpoints).
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.clients.models import Client


class IsAuthenticatedClient(BasePermission):
    message = "A valid client session is required."

    def has_permission(self, request, view) -> bool:
        return isinstance(getattr(request, "user", None), Client) and request.user.is_active


class HasSignedNDA(BasePermission):
    message = "This resource requires a signed NDA."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return isinstance(user, Client) and user.is_active and user.nda_signed
