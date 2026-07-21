"""
Customer-success permissions (Backend v6.0 §Phase 2).

``IsContractedCustomer`` is the gate for the customer_contract tier. It is deliberately
STRICTER than ``IsAuthenticatedClient``: a client with a signed NDA is not yet a
customer, and the sixth disclosure tier belongs to customers only.

── WHY THE OVERLAY GATE IS SEPARATE ─────────────────────────────────────────
``HasSuccessOverlay`` answers a different question: has this client reached the point
where customer-success MODULES activate? That is the FIRST PAYMENT (R16), not the
contract. A paid Assessment customer sees owners, support and goals long before any
license is executed — so the two gates cannot be the same check.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.clients.models import Client

# Contract states that count as "contracted".
CONTRACTED_STATES = {"executed", "active", "contracted"}


class IsContractedCustomer(BasePermission):
    """Gates the customer_contract disclosure tier."""

    message = "This resource is available to contracted customers."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not isinstance(user, Client) or not user.is_active:
            return False
        return (getattr(user, "contract_state", "") or "") in CONTRACTED_STATES


class HasSuccessOverlay(BasePermission):
    """
    Gates the customer-success surface.

    Activates at FIRST PAYMENT, not at license-out. This is the whole point of R16:
    a paying customer gets support and named owners immediately, not eventually.
    """

    message = "The customer-success workspace activates once a first payment is recorded."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not isinstance(user, Client) or not user.is_active:
            return False
        if getattr(user, "first_payment_recorded_at", None):
            return True
        # A contracted customer always has it, even if the payment timestamp is missing
        # (a data gap must not withdraw support access from someone who is paying).
        return (getattr(user, "contract_state", "") or "") in CONTRACTED_STATES
