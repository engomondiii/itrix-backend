"""
The shell contract — ``services/shell.py`` (Backend v6.0 §3.1).

This module REPLACES the planned ``services/rails.py``. It never shipped, so there is no
rails module to delete: shell.py supersedes it before it exists.

``shell.for_subject(subject)`` is the SINGLE AUTHORITY for what Surface 1 may render. It
returns the full shell contract:

    {
      "thread_id", "journey_state", "state_key", "identity_state",
      "disclosure_ceiling", "value_delivered", "current_work",
      "composer_label", "question_loop_open", "attachments_enabled",
      "sidebar_sections", "conversation_header", "next_best_action"
    }

Four rules make this load-bearing rather than decorative:

1. ``left_rail`` and ``right_rail`` are GONE. For one release the serializer still emits
   them as ``[]`` / ``null`` with a deprecation header (see ``apps/journey/serializers.py``);
   after that they are absent and a client that sends them receives 400.

2. ``identity_state == "anonymous"`` suppresses EVERY section that could name an
   organisation, at any state. An anonymous socket that somehow reached State 7 still
   sees only the base sections.

3. Section keys are a CLOSED vocabulary in ``constants.py``. An unknown key is a SERVER
   ERROR (``UnknownSidebarSection``), not a silent skip — a typo must fail loudly in CI
   rather than quietly hide a section the subject was entitled to.

4. A section with no authorized content is OMITTED, not returned empty. The frontend
   never has to decide whether an empty section should render.

The frontend MIRRORS the vocabulary from ``constants.py``; it never re-decides it.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.journey.constants import (
    BASE_SIDEBAR_SECTIONS,
    COMPOSER_LABELS,
    IDENTITY_ANONYMOUS,
    IDENTITY_AUTHENTICATED_CUSTOMER,
    IDENTITY_IDENTIFIED,
    ORGANISATION_REVEALING_SECTIONS,
    SIDEBAR_SECTIONS_BY_STATE,
    STATE_CHIP_LABELS,
    min_ceiling,
    validate_sidebar_sections,
)
from apps.journey.models import (
    JourneyState,
    ceiling_for_state,
    journey_number,
    normalize_state,
)

logger = logging.getLogger("itrix")


class UnknownSidebarSection(Exception):
    """
    Raised when a section key is not in the closed vocabulary.

    This is deliberately an exception rather than a filtered-out key: silently dropping
    an unrecognised section would hide a regression instead of surfacing it.
    """


# The ceiling each identity plane may reach. The PLANE always wins over the state
# (Architecture v2.6 §12.1) — a state can only ever narrow, never widen.
_PLANE_CEILING = {
    IDENTITY_ANONYMOUS: "controlled_public",
    IDENTITY_IDENTIFIED: "nda_only",
    IDENTITY_AUTHENTICATED_CUSTOMER: "customer_contract",
}

# What "current work" a state represents, for the conversation header.
_CURRENT_WORK = {
    1: {"type": "review", "status": "not_started"},
    2: {"type": "review", "status": "in_progress"},
    3: {"type": "review", "status": "reflected"},
    4: {"type": "pitch", "status": "delivered"},
    5: {"type": "pitch", "status": "qualified"},
    6: {"type": "nda", "status": "in_progress"},
    7: {"type": "assessment", "status": "in_progress"},
    8: {"type": "poc", "status": "in_progress"},
    9: {"type": "integration", "status": "in_progress"},
    10: {"type": "customer_outcome", "status": "active"},
}


def resolve_identity_state(subject) -> str:
    """
    Derive ``identity_state`` from what the subject actually is.

    anonymous              — no client account, no verified email
    identified             — a Client account exists (or the lead volunteered an email)
    authenticated_customer — the client holds an executed contract

    NOTE this is derived, never asserted by the caller. A visitor cannot claim to be
    identified; they become identified by creating an account.
    """
    client = getattr(subject, "client", None)
    if client is None:
        client_id = getattr(subject, "client_id", "") or ""
        if client_id:
            try:
                from apps.clients.models import Client

                client = Client.objects.filter(id=client_id).first()
            except Exception:  # noqa: BLE001 - clients app optional at import time
                client = None

    if client is not None:
        contract_state = getattr(client, "contract_state", "") or ""
        if contract_state in {"executed", "active", "contracted"}:
            return IDENTITY_AUTHENTICATED_CUSTOMER
        return IDENTITY_IDENTIFIED

    # A lead that volunteered an email has self-identified, but has no workspace.
    if (getattr(subject, "email", "") or "").strip():
        return IDENTITY_IDENTIFIED
    return IDENTITY_ANONYMOUS


def sidebar_sections_for(
    state: str, identity_state: str = IDENTITY_ANONYMOUS
) -> list[str]:
    """
    The ordered, authorized sidebar sections for ``state`` on this identity plane.

    Always includes the base set — brand_nav, new_review, conversations, explore, legal
    — so a visitor with nothing authorized still has orientation and a route to policy
    (Architecture v2.6 §16.2).
    """
    number = journey_number(state)
    extra: tuple[str, ...] = () if number is None else SIDEBAR_SECTIONS_BY_STATE.get(number, ())

    sections = set(BASE_SIDEBAR_SECTIONS) | set(extra)

    # RULE 2: anonymous suppresses every section that could name an organisation.
    if identity_state == IDENTITY_ANONYMOUS:
        sections -= ORGANISATION_REVEALING_SECTIONS

    try:
        return validate_sidebar_sections(sections)
    except ValueError as exc:
        # RULE 3: an unknown key is a server error, not a silent skip.
        raise UnknownSidebarSection(str(exc)) from exc


def composer_label_for(state: str) -> str:
    """One composer at every state; only the label changes (§16.3)."""
    return COMPOSER_LABELS.get(normalize_state(state), COMPOSER_LABELS["ARRIVED"])


def disclosure_ceiling_for(state: str, identity_state: str, *, nda_signed: bool = False) -> str:
    """
    The effective ceiling: the MORE RESTRICTIVE of the plane's ceiling and the state's.

    The plane can never be raised by the state, by a prompt, or by an attachment
    (Architecture v2.6 §19.7 rule 6). ``nda_signed`` can only ever narrow the gap
    between an identified client's cap and nda_only — never exceed the plane.
    """
    plane_cap = _PLANE_CEILING.get(identity_state, "public")
    if identity_state == IDENTITY_IDENTIFIED and not nda_signed:
        plane_cap = "controlled_public"
    return min_ceiling(plane_cap, ceiling_for_state(state))


def conversation_header_for(subject, state: str, identity_state: str) -> dict[str, Any]:
    """
    The conversation header — continuity and reach (Architecture v2.6 §11.6A).

    This is where the retired right rail's two non-negotiable payloads now live:
    the NAMED OWNER and QUICK HELP. R30 is an absolute: a named human is reachable in
    one action at every state. ``quick_help`` is therefore always True from
    identification onward and is never conditional on a feature flag.
    """
    normalized = normalize_state(state)
    title = (getattr(subject, "compute_bottleneck", "") or "").strip()
    if len(title) > 80:
        title = title[:77].rstrip() + "..."

    owner = getattr(subject, "owner", None)
    owner_name = ""
    if owner is not None and identity_state != IDENTITY_ANONYMOUS:
        owner_name = (
            getattr(owner, "full_name", "")
            or getattr(owner, "get_full_name", lambda: "")()
            or getattr(owner, "email", "")
            or ""
        )

    return {
        "title": title or "New review",
        "state_label": STATE_CHIP_LABELS.get(normalized, "Review"),
        # Name and role only — never an inferred organisation.
        "human_owner": owner_name or None,
        "support_sla": _support_sla_for(normalized),
        # R30: always reachable once the subject is identified.
        "quick_help": identity_state != IDENTITY_ANONYMOUS,
    }


def _support_sla_for(state: str) -> str | None:
    """The SLA badge shown from State 7 (the first PAID rung) onward."""
    number = journey_number(state)
    if number is None or number < 7:
        return None
    from django.conf import settings

    hours = int(getattr(settings, "SUPPORT_SLA_DEFAULT_HOURS", 4))
    return f"{hours}h"


def for_subject(subject, *, thread=None, identity_state: str | None = None) -> dict[str, Any]:
    """
    Build the complete shell contract for ``subject`` (a Lead).

    ``thread`` is the active Thread, when one is known. ``identity_state`` may be passed
    by a caller that already resolved it (e.g. the client-plane view); otherwise it is
    DERIVED — never trusted from the request.
    """
    state = normalize_state(getattr(subject, "journey_state", None))
    number = journey_number(state)
    resolved_identity = identity_state or resolve_identity_state(subject)

    nda_signed = bool(getattr(subject, "nda_signed_at", None)) or _has_signed_nda(subject)
    ceiling = disclosure_ceiling_for(state, resolved_identity, nda_signed=nda_signed)

    # Gates are deterministic and live in gate.py — shell only READS them.
    from apps.journey.services.gate import question_loop_open

    contract: dict[str, Any] = {
        "thread_id": str(getattr(thread, "id", "") or "") or None,
        "journey_state": number,
        "state_key": state,
        "identity_state": resolved_identity,
        "disclosure_ceiling": ceiling,
        "value_delivered": getattr(subject, "value_delivered_at", None) is not None,
        "current_work": _CURRENT_WORK.get(number or 1, _CURRENT_WORK[1]),
        "composer_label": composer_label_for(state),
        "question_loop_open": question_loop_open(subject),
        "attachments_enabled": _attachments_enabled(),
        "sidebar_sections": sidebar_sections_for(state, resolved_identity),
        "conversation_header": conversation_header_for(subject, state, resolved_identity),
        # Phase 3 populates this through nba_precedence; Phase 1 emits None rather than
        # an unsuppressed commercial action, which would violate the customer-first rule.
        "next_best_action": None,
    }
    return contract


def _attachments_enabled() -> bool:
    """Attachments are a Phase-2 subsystem; the flag gates the attach control."""
    from django.conf import settings

    return bool(getattr(settings, "ENABLE_ATTACHMENTS", False))


def _has_signed_nda(subject) -> bool:
    """Best-effort NDA lookup — never raises if the nda app is unavailable."""
    try:
        from apps.nda.models import NDARecord

        return NDARecord.objects.filter(lead=subject, signed_at__isnull=False).exists()
    except Exception:  # noqa: BLE001
        return False


def for_anonymous_thread(thread) -> dict[str, Any]:
    """
    The shell contract for a thread that has NO lead yet (State 1, first visit).

    A visitor gets a thread from their very first sentence, before any Lead exists. This
    returns the minimum-privilege shell: state 1, public ceiling, base sections only.
    """
    return {
        "thread_id": str(getattr(thread, "id", "") or "") or None,
        "journey_state": 1,
        "state_key": JourneyState.ARRIVED.value,
        "identity_state": IDENTITY_ANONYMOUS,
        "disclosure_ceiling": "public",
        "value_delivered": False,
        "current_work": _CURRENT_WORK[1],
        "composer_label": composer_label_for(JourneyState.ARRIVED.value),
        "question_loop_open": True,
        "attachments_enabled": _attachments_enabled(),
        "sidebar_sections": sidebar_sections_for(
            JourneyState.ARRIVED.value, IDENTITY_ANONYMOUS
        ),
        "conversation_header": {
            "title": (getattr(thread, "title", "") or "New review"),
            "state_label": STATE_CHIP_LABELS["ARRIVED"],
            "human_owner": None,
            "support_sla": None,
            "quick_help": False,
        },
        "next_best_action": None,
    }
