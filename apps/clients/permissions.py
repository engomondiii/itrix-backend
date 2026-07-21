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


# ── v6.0 Phase 2 ─────────────────────────────────────────────────────────────
# Re-exported so callers have ONE import site for client-plane permissions and cannot
# accidentally use a laxer gate than they meant to.
from apps.customer_success.permissions import (  # noqa: E402,F401
    CONTRACTED_STATES,
    HasSuccessOverlay,
    IsContractedCustomer,
)


def ceiling_for_client(client) -> str:
    """
    The disclosure ceiling a client may reach.

    Extended in v6.0 with the sixth tier. The ordering is strict and each step must be
    EARNED — a contract implies an NDA, but an NDA never implies a contract:

        no NDA        -> controlled_public
        NDA signed    -> nda_only
        contracted    -> customer_contract
    """
    if client is None or not getattr(client, "is_active", False):
        return "public"
    if (getattr(client, "contract_state", "") or "") in CONTRACTED_STATES:
        return "customer_contract"
    if getattr(client, "nda_signed", False):
        return "nda_only"
    return "controlled_public"
