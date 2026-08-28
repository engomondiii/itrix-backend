"""Deterministic routing for the customer-success "What can we improve?" composer.

This is triage, not generation: support problems become durable SupportRequests; requests
about outcomes/training and other relationship improvements become private feedback pulses
with human follow-up requested. The customer is told where it went, never asked to choose
an internal department.
"""
from __future__ import annotations

import re

from apps.customer_success.services import feedback_pulse, support_router

_TRAINING = re.compile(r"\b(training|documentation|docs|guide|learn|onboard|enablement|workshop)\b", re.I)
_OUTCOME = re.compile(r"\b(outcome|goal|target|metric|kpi|success criteria|milestone|plan)\b", re.I)


def route(client, message: str) -> dict:
    text = " ".join((message or "").split())
    if not text:
        raise ValueError("message_required")

    if support_router.detect_support_intent(text):
        request = support_router.route(client, text)
        return {
            "route": "support",
            "owner": request.owner_name or None,
            "acknowledgement": support_router.acknowledge_copy(request),
        }

    if _TRAINING.search(text):
        route_name = "training"
    elif _OUTCOME.search(text):
        route_name = "outcome"
    else:
        route_name = "human"

    # Keep the message as private relationship feedback, with explicit follow-up. This
    # avoids inventing a second task model while still making the composer durable.
    feedback_pulse.submit(client, score=None, comment=text, wants_follow_up=True)
    owner = _owner_name(client)
    labels = {
        "training": "training and enablement",
        "outcome": "your shared outcomes",
        "human": "your itriX relationship team",
    }
    return {
        "route": route_name,
        "owner": owner,
        "acknowledgement": f"We have this. It has been routed to {labels[route_name]} for follow-up.",
    }


def _owner_name(client) -> str | None:
    from apps.customer_success.models import RelationshipTeamMember

    member = (
        RelationshipTeamMember.objects.filter(client=client, role="customer_success").first()
        or RelationshipTeamMember.objects.filter(client=client, is_primary=True).first()
    )
    if member is None:
        return None
    return getattr(member, "display_name", "") or None
