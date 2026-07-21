"""
The success overlay — reveal 5 (Backend v6.0 §Phase 2, Architecture §7.1, R16).

    activate(client)  -> seeds the relationship team, support access and success goals

── THE RULE THIS IMPLEMENTS ─────────────────────────────────────────────────
Customer-success modules activate at the FIRST PAYMENT, not at license-out.

That is not a scheduling detail. A customer who has just paid for an Assessment is
already exposed: they have committed money and have nobody named to call. Waiting until
license-out to give them an owner means the riskiest period of the relationship is the
one with the least support.

``activate()`` is idempotent — it is called from ``journey.advance`` on FIRST_PAYMENT,
and a retried transition must not duplicate a relationship team.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("itrix")

# The four roles every customer gets. Support is listed last because it is the one they
# reach in an emergency, and it must never be the only one present.
DEFAULT_ROLES = (
    ("customer_success", "Day-to-day, outcomes, and anything that is not working."),
    ("technical", "The workload, the deployment, and the numbers."),
    ("executive", "Commercial questions and anything needing a decision above the working level."),
    ("support", "Anything urgent."),
)


@transaction.atomic
def activate(client, *, actor=None) -> dict:
    """
    Activate the customer-success overlay for ``client``.

    Idempotent. Returns a summary of what was created so the caller can log it.
    """
    from apps.customer_success.models import RelationshipTeamMember

    if client is None:
        return {"activated": False, "reason": "no client"}

    already = bool(getattr(client, "first_payment_recorded_at", None))
    created_roles: list[str] = []

    if not already:
        client.first_payment_recorded_at = timezone.now()
        fields = ["first_payment_recorded_at", "updated_at"]
        # Health starts UNKNOWN, not "stable". Asserting stability we have not measured
        # would let expansion_allowed authorize a sale on an assumption.
        client.save(update_fields=fields)

    for role, helps_with in DEFAULT_ROLES:
        _member, was_created = RelationshipTeamMember.objects.get_or_create(
            client=client,
            role=role,
            defaults={
                "display_name": _default_name_for(role, client),
                "helps_with": helps_with,
                "is_primary": role == "customer_success",
            },
        )
        if was_created:
            created_roles.append(role)

    logger.info(
        "customer_success.overlay activated for client=%s (new roles: %s)",
        client.id,
        created_roles or "none",
    )
    return {
        "activated": True,
        "first_payment_recorded": not already,
        "roles_created": created_roles,
    }


def _default_name_for(role: str, client) -> str:
    """
    A placeholder name until a real person is assigned.

    Deliberately NOT "TBD" or an empty string: the header renders this, and a customer
    who is told they have a named owner and then sees "TBD" has been told something
    untrue. "itriX Customer Success" is honest — it names the team, not a fiction.
    """
    return {
        "customer_success": "itriX Customer Success",
        "technical": "itriX Technical Review",
        "executive": "itriX Executive Sponsor",
        "support": "itriX Support",
    }.get(role, "itriX Team")


def is_active(client) -> bool:
    """Whether the overlay is live for this client."""
    if client is None:
        return False
    if getattr(client, "first_payment_recorded_at", None):
        return True
    from apps.customer_success.permissions import CONTRACTED_STATES

    return (getattr(client, "contract_state", "") or "") in CONTRACTED_STATES
