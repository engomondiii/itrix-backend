"""
The shell contract — ``services/shell.py`` (Backend v6.0 §3.1).

This module REPLACES the planned ``services/rails.py``. It never shipped, so there is no
rails module to delete: shell.py supersedes it before it exists.

``shell.for_subject(subject)`` is the SINGLE AUTHORITY for what Surface 1 may render. It
returns the full shell contract:

    {
      "thread_id", "shell_mode", "journey_state", "state_key", "identity_state",
      "disclosure_ceiling", "value_delivered", "current_work",
      "composer_label", "question_loop_open", "attachments_enabled",
      "conversation_rail_sections", "content_pane_sections",
      "content_pane_default_artifact_id",
      "conversation_header", "next_best_action"
    }

── v7.1 PHASE 1: THE ZONE VOCABULARY SPLITS IN TWO ─────────────────────────

``sidebar_sections`` is superseded by ``conversation_rail_sections`` and
``content_pane_sections`` (Architecture v2.8 §11.6). The rail is THREE keys and never
grows; the pane is seventeen and is the zone that does.

── v7.1 PHASE 3: ``sidebar_sections`` IS GONE ──────────────────────────────
It was emitted as an ALIAS OF THE RAIL through Phases 1 and 2, giving both frontends a full
release to migrate. It is now ABSENT.

The alias was the rail, never the union of both zones — emitting the union would have put
pane sections back into a sidebar on an un-migrated client, which is the exact regression the
split existed to prevent. Both surfaces now read ``conversation_rail_sections``, so the alias
has no readers left and keeping it would only invite a new one.

``left_rail`` and ``right_rail`` were retired the same way in v6.0 Phase 3, and a client that
still SENDS them receives 400 rather than silence
(``apps/conversations/serializers_thread.py``). The same posture applies here: a field we no
longer honour must not be silently accepted, because that leaves a frontend believing it still
controls something it does not.

Six rules make this load-bearing rather than decorative:

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

5. ``shell_mode`` IS DERIVED HERE AND NOWHERE ELSE. A client that decided its own mode
   could render a rail to a visitor the backend has not authorized one for. The threshold
   is whether a thread exists AND carries a visitor turn — not the journey state, which
   can lag a turn behind.

6. THE PANE NEVER CARRIES what §11.6A re-homed: no next-best-action, no confidentiality
   notice, no quick help, no specialist card, no scheduling card, no satisfaction pulse.
   Those six are how a visitor reaches a human and how they know what not to send us, so
   they must not live in a panel the visitor can collapse. There is no pane payload in
   this module that could carry one.

The frontend MIRRORS the vocabulary from ``constants.py``; it never re-decides it.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.journey.constants_zones import (
    BASE_PANE_SECTIONS,
    CONTENT_PANE_SECTIONS_BY_STATE,
    CONVERSATION_RAIL_SECTIONS,
    ORGANISATION_REVEALING_PANE_SECTIONS,
    SHELL_MODE_ARRIVAL,
    SHELL_MODE_WORKING,
    UnknownZoneSection,
    validate_pane_sections,
    validate_rail_sections,
)
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


def conversation_rail_sections_for(
    state: str, identity_state: str = IDENTITY_ANONYMOUS
) -> list[str]:
    """
    The conversation rail. THREE KEYS, AT EVERY STATE, ON EVERY PLANE.

    ``state`` and ``identity_state`` are accepted and deliberately unused: the signature
    matches the pane builder so a future change cannot make the rail state-dependent
    without editing this docstring first.

    The rail never grows (Architecture v2.8 §11.6). In v6.0 the sidebar gained a section
    per state and carried fourteen by State 10, which made it a navigation menu that
    happened to contain conversations. Its job is to name conversations.

    Nor is it suppressed on the anonymous plane. `new_chat`, `conversations` and
    `account` are ORIENTATION rather than entitlement: a visitor with no relationship
    still needs a way to start a conversation and find the ones they already have. None
    of the three can name an organisation.
    """
    del state, identity_state  # see the docstring — intentionally not consulted
    return validate_rail_sections(CONVERSATION_RAIL_SECTIONS)


def content_pane_sections_for(
    state: str, identity_state: str = IDENTITY_ANONYMOUS
) -> list[str]:
    """
    The ordered, authorized content-pane sections for ``state`` on this plane.

    Always includes ``explore`` and ``legal``, at every state and on every plane. They are
    orientation rather than entitlement, and ``legal`` in particular is not optional: the
    four instruments are "not permitted to disappear at any width" (§2.4), and the pane is
    one of only two places they live.

    ``identity_state == "anonymous"`` suppresses every section that could name an
    organisation, at ANY state — the same rule the v6.0 sidebar had, carried forward. An
    anonymous socket that somehow reached State 7 still sees only the base sections plus
    its own artifacts.
    """
    number = journey_number(state)
    extra: tuple[str, ...] = (
        () if number is None else CONTENT_PANE_SECTIONS_BY_STATE.get(number, ())
    )

    sections = set(BASE_PANE_SECTIONS) | set(extra)

    if identity_state == IDENTITY_ANONYMOUS:
        sections -= ORGANISATION_REVEALING_PANE_SECTIONS

    try:
        return validate_pane_sections(sections)
    except UnknownZoneSection:
        raise
    except ValueError as exc:  # pragma: no cover - defensive
        raise UnknownZoneSection(str(exc)) from exc


def shell_mode_for(thread) -> str:
    """
    ``arrival`` or ``working`` — DERIVED HERE, never asserted by a client (§2.6).

    ── THE THRESHOLD IS THE VISITOR'S OWN FIRST SENTENCE ───────────────────
    Not the journey state. State can lag a turn behind: a visitor who has just submitted
    is still at ARRIVED until the router advances them, and showing them the bare front
    door with their own words already on screen would be wrong.

    So: a thread with at least one visitor turn is WORKING. No thread, or a thread with
    nothing in it, is ARRIVAL.

    ``arrival`` is the fail-safe. Anything unexpected resolves to the mode that renders
    least — no rail, no pane, no navigation.
    """
    if thread is None or not getattr(thread, "id", None):
        return SHELL_MODE_ARRIVAL

    try:
        from apps.conversations.models import Message

        has_turn = Message.objects.filter(
            thread_id=thread.id, sender_kind="visitor"
        ).exists()
    except Exception:  # noqa: BLE001 - never let a mode lookup break the shell
        logger.warning("shell_mode: could not read turns for thread %s", getattr(thread, "id", "?"))
        return SHELL_MODE_ARRIVAL

    return SHELL_MODE_WORKING if has_turn else SHELL_MODE_ARRIVAL


def content_pane_default_artifact_id(thread, sections) -> str | None:
    """
    Which artifact the pane opens on.

    The NEWEST APPROVED artifact in the thread, and None when there is none. Never an
    arbitrary index, and never a pinned artifact: ``success_overview`` is standing context
    above the transcript, so pointing the pane at it would show the same thing twice.

    Returns None when the pane has no ``artifacts`` section, because a default for a
    section the subject cannot see is a default that cannot be honoured.
    """
    if thread is None or "artifacts" not in set(sections):
        return None

    try:
        from apps.journey.models_artifacts import Artifact

        # ``Artifact`` has NO ``seq`` column — an earlier draft ordered by one. The real
        # ordering keys are ``version`` and ``created_at``, and a PINNED artifact is
        # excluded rather than ranked: ``success_overview`` is standing context above the
        # transcript, so pointing the pane at it would show the same thing twice.
        artifact = (
            Artifact.objects.filter(thread_id=thread.id, governance_status="approved")
            .filter(pinned=False)
            .order_by("-created_at", "-version")
            .first()
        )
    except Exception:  # noqa: BLE001
        return None

    return str(artifact.id) if artifact is not None else None


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

    pane_sections = content_pane_sections_for(state, resolved_identity)
    rail_sections = conversation_rail_sections_for(state, resolved_identity)

    contract: dict[str, Any] = {
        "thread_id": str(getattr(thread, "id", "") or "") or None,
        # v7.1: derived here and nowhere else (§2.6). A client that decided its own mode
        # could render a rail to a visitor the backend has not authorized one for.
        "shell_mode": shell_mode_for(thread),
        "journey_state": number,
        "state_key": state,
        "identity_state": resolved_identity,
        "disclosure_ceiling": ceiling,
        "value_delivered": getattr(subject, "value_delivered_at", None) is not None,
        "current_work": _CURRENT_WORK.get(number or 1, _CURRENT_WORK[1]),
        "composer_label": composer_label_for(state),
        "question_loop_open": question_loop_open(subject),
        "attachments_enabled": _attachments_enabled(),
        # ── v7.1: the two zones ─────────────────────────────────────────────
        "conversation_rail_sections": rail_sections,
        "content_pane_sections": pane_sections,
        "content_pane_default_artifact_id": content_pane_default_artifact_id(
            thread, pane_sections
        ),
        "conversation_header": conversation_header_for(subject, state, resolved_identity),
        # v7.1 PHASE 3 — ONE NBA FOR BOTH PLANES (§11.1). See next_best_action_for.
        "next_best_action": next_best_action_for(subject),
    }
    return contract


def next_best_action_for(subject) -> dict | None:
    """
    The subject's next best action, THROUGH THE SAME RULE THE COCKPIT USES.

    ── WHY THIS FUNCTION EXISTS AT ALL ─────────────────────────────────────
    The cockpit path has gone through ``nba_precedence`` since v6.0 Phase 3
    (``CockpitNextActionView``). The PORTAL path returned ``None`` — a placeholder Phase 1
    left with a note saying Phase 3 would fill it.

    That asymmetry was the safe direction to be wrong in, and it was still wrong. §11.1 says
    the two planes pass through one rule so a customer and an operator can never see
    contradictory guidance; with one side returning nothing, they could not contradict each
    other but they also could not agree. A customer saw no next step while their operator saw
    a governed one.

    ── THE CLIENT PAYLOAD CARRIES NO SUPPRESSION REASON ────────────────────
    ``to_client_payload()`` returns the action and nothing about what was withheld
    (§10.5). A customer does not need to be told we decided not to sell to them today, and
    telling them would be a strange kind of honesty: it would surface a commercial
    deliberation they never asked to be part of.

    ── AND IT FAILS TO None, NOT TO A COMMERCIAL ACTION ────────────────────
    Every failure path here returns None. That is the direction that matters: an
    unsuppressed commercial action shown to a customer with a blocking support request open
    is the precise defect §18.7 exists to prevent, so "no action" is always the safer
    answer than "the highest-weighted one we could still compute".
    """
    if subject is None:
        return None

    try:
        from apps.agents.services.strategy import nba_candidates
        from apps.governance.services import nba_precedence

        candidates = nba_candidates(subject)
        if not candidates:
            return None

        decision = nba_precedence.for_lead(subject, candidates)
        return decision.to_client_payload()
    except Exception:  # noqa: BLE001
        logger.exception(
            "shell.next_best_action_failed subject=%s — emitting None rather than an "
            "ungoverned action",
            getattr(subject, "id", "?"),
        )
        return None


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
    pane_sections = content_pane_sections_for(
        JourneyState.ARRIVED.value, IDENTITY_ANONYMOUS
    )
    rail_sections = conversation_rail_sections_for(
        JourneyState.ARRIVED.value, IDENTITY_ANONYMOUS
    )

    return {
        "thread_id": str(getattr(thread, "id", "") or "") or None,
        # A thread exists, so the mode depends on whether anything has been said in it.
        # A visitor who has just typed their first sentence is WORKING even though no
        # Lead exists yet.
        "shell_mode": shell_mode_for(thread),
        "journey_state": 1,
        "state_key": JourneyState.ARRIVED.value,
        "identity_state": IDENTITY_ANONYMOUS,
        "disclosure_ceiling": "public",
        "value_delivered": False,
        "current_work": _CURRENT_WORK[1],
        "composer_label": composer_label_for(JourneyState.ARRIVED.value),
        "question_loop_open": True,
        "attachments_enabled": _attachments_enabled(),
        "conversation_rail_sections": rail_sections,
        "content_pane_sections": pane_sections,
        "content_pane_default_artifact_id": content_pane_default_artifact_id(
            thread, pane_sections
        ),
        "conversation_header": {
            "title": (getattr(thread, "title", "") or "New review"),
            "state_label": STATE_CHIP_LABELS["ARRIVED"],
            "human_owner": None,
            "support_sla": None,
            "quick_help": False,
        },
        # No Lead exists yet, so there is no subject to reason about — and nothing the
        # precedence rule could read. None is the honest answer rather than a placeholder.
        "next_best_action": None,
    }
