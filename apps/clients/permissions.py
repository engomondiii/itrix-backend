"""
Client-plane permissions.

``IsAuthenticatedClient`` passes only when the request was authenticated by
``ClientJWTAuthentication`` (i.e. ``request.user`` is a ``Client``). Team users and
anonymous requests are rejected — the client plane is separate from the team plane.

``HasSignedNDA`` is a narrow agreement-prerequisite helper. It must never be used as a
content-authorization gate: restricted Knowledge material also requires an explicit
``ContentAuthorization`` for the current subject and document.
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


# ── v6.0 Phase 2 ─────────────────────────────────────────────────────────────
# Re-exported so callers have ONE import site for client-plane permissions and cannot
# accidentally use a laxer gate than they meant to.
from apps.customer_success.permissions import (  # noqa: E402,F401
    CONTRACTED_STATES,
    HasSuccessOverlay,
    IsContractedCustomer,
)


def ceiling_for_client(client) -> str:
    """Return the client plane's baseline ceiling.

    Account state, email verification, identity verification, NDA and contract state are
    not blanket disclosure grants. Restricted documents are permitted only through the
    explicit ContentAuthorization gate in Knowledge Core.
    """
    if client is None or not getattr(client, "is_active", False):
        return "public"
    return "controlled_public"
