"""
Journey constants — the closed vocabularies (Backend v6.0 §3.1, §3.2).

This module is the SINGLE SOURCE for four vocabularies that both frontends mirror but
never re-decide:

    JOURNEY_NUMBERS   state_key -> 1..10 (DORMANT is off-ladder and has no number)
    STATE_KEYS        the ordered state keys
    SIDEBAR_SECTIONS  the closed sidebar-section vocabulary + per-state growth
    ARTIFACT_TYPES    the closed artifact-type vocabulary

Rules that make these load-bearing rather than decorative:

* An unknown sidebar-section key is a SERVER ERROR, not a silent skip. ``shell.py``
  raises ``UnknownSidebarSection`` so a typo is caught in CI rather than silently
  dropping a section the visitor was entitled to see.
* An unknown artifact type is a server error for the same reason (§11.1 Integration).
* ``itrix-web/src/lib/journey/sidebarSections.ts`` and
  ``itrix-web/src/lib/journey/artifactTypes.ts`` MIRROR this file. If you change a key
  here, change it there in the same PR. ``SIDEBAR_SECTION_ORDER`` is the canonical
  ordering the frontend renders in.

Nothing in this module imports Django models, so it is safe to import from migrations,
management commands, tests and settings.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# The ten states (Architecture v2.6 §11.1)
# ─────────────────────────────────────────────────────────────────────────────
# state_key -> journey_number. DORMANT is retained as an OFF-LADDER state: it is a
# real state value but carries no number, so it never appears in the ladder UI and
# never participates in "how far along is this subject" arithmetic.
JOURNEY_NUMBERS: dict[str, int] = {
    "ARRIVED": 1,
    "IN_REVIEW": 2,
    "DIAGNOSED": 3,
    "CLIENT_PAGE": 4,
    "INVITED": 5,
    "NDA_REVIEW": 6,
    "ASSESSMENT": 7,
    "POC": 8,
    "INTEGRATION": 9,
    "CUSTOMER_SUCCESS": 10,
}

# The ordered state keys (ladder order). DORMANT deliberately excluded.
STATE_KEYS: tuple[str, ...] = tuple(
    sorted(JOURNEY_NUMBERS, key=lambda key: JOURNEY_NUMBERS[key])
)

# Off-ladder states — real values, no journey_number.
OFF_LADDER_STATES: frozenset[str] = frozenset({"DORMANT"})

# Reverse lookup: 1..10 -> state_key.
STATE_KEY_BY_NUMBER: dict[int, str] = {n: k for k, n in JOURNEY_NUMBERS.items()}

# Plain-language state chip labels (Playbook v1.6 §16E). NEVER a stage number,
# never a tier, never a score.
STATE_CHIP_LABELS: dict[str, str] = {
    "ARRIVED": "Review",
    "IN_REVIEW": "Review",
    "DIAGNOSED": "Reflection",
    "CLIENT_PAGE": "Your brief",
    "INVITED": "Qualified",
    "NDA_REVIEW": "NDA",
    "ASSESSMENT": "Assessment",
    "POC": "PoC",
    "INTEGRATION": "Integration",
    "CUSTOMER_SUCCESS": "Customer success",
    "DORMANT": "Review",
}

# ─────────────────────────────────────────────────────────────────────────────
# Composer labels (Architecture v2.6 §16.3 / Playbook v1.6 Part IV)
# ─────────────────────────────────────────────────────────────────────────────
# One composer at every state. ONLY the label changes.
COMPOSER_LABEL_ARRIVAL = "What would you like computation to do better?"
COMPOSER_LABEL_DEFAULT = "Ask itriX"
COMPOSER_LABEL_SUCCESS = "What can we improve for you?"

COMPOSER_LABELS: dict[str, str] = {
    "ARRIVED": COMPOSER_LABEL_ARRIVAL,
    "IN_REVIEW": COMPOSER_LABEL_DEFAULT,
    "DIAGNOSED": COMPOSER_LABEL_DEFAULT,
    "CLIENT_PAGE": COMPOSER_LABEL_DEFAULT,
    "INVITED": COMPOSER_LABEL_DEFAULT,
    "NDA_REVIEW": COMPOSER_LABEL_DEFAULT,
    "ASSESSMENT": COMPOSER_LABEL_DEFAULT,
    "POC": COMPOSER_LABEL_DEFAULT,
    "INTEGRATION": COMPOSER_LABEL_DEFAULT,
    "CUSTOMER_SUCCESS": COMPOSER_LABEL_SUCCESS,
    "DORMANT": COMPOSER_LABEL_ARRIVAL,
}

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar sections (Architecture v2.6 §11.6, Backend v6.0 §3.2)
# ─────────────────────────────────────────────────────────────────────────────
# The CLOSED vocabulary. `shell.py` refuses to emit anything not in this set.
SIDEBAR_SECTIONS: frozenset[str] = frozenset(
    {
        # Always present — the visitor always has orientation and a route to policy.
        "brand_nav",
        "new_review",
        "conversations",
        "explore",
        "legal",
        # States 4-5
        "documents",
        "pathway",
        # State 6
        "nda",
        # State 7
        "workspace_assessment",
        "decisions",
        # State 8
        "workspace_poc",
        # State 9
        "workspace_integration",
        "governance",
        # State 10
        "outcomes",
        "deployments",
        "support",
        "knowledge",
        "meetings",
        "feedback",
    }
)

# The canonical render order. The frontend renders sections in THIS order, not in the
# order the payload happens to arrive.
SIDEBAR_SECTION_ORDER: tuple[str, ...] = (
    "brand_nav",
    "new_review",
    "conversations",
    "documents",
    "pathway",
    "nda",
    "workspace_assessment",
    "workspace_poc",
    "workspace_integration",
    "decisions",
    "governance",
    "outcomes",
    "deployments",
    "support",
    "knowledge",
    "meetings",
    "feedback",
    "explore",
    "legal",
)

# Sections present at EVERY state, including State 1 with an empty conversation list.
BASE_SIDEBAR_SECTIONS: tuple[str, ...] = (
    "brand_nav",
    "new_review",
    "conversations",
    "explore",
    "legal",
)

# What each state ADDS on top of the base set (Backend v6.0 §3.2).
# States 2-3 add nothing: the thread itself carries the memory.
SIDEBAR_SECTIONS_BY_STATE: dict[int, tuple[str, ...]] = {
    1: (),
    2: (),
    3: (),
    4: ("documents", "pathway"),
    5: ("documents", "pathway"),
    6: ("documents", "pathway", "nda"),
    7: ("documents", "pathway", "nda", "workspace_assessment", "decisions"),
    8: (
        "documents",
        "pathway",
        "nda",
        "workspace_assessment",
        "decisions",
        "workspace_poc",
    ),
    9: (
        "documents",
        "pathway",
        "nda",
        "workspace_assessment",
        "decisions",
        "workspace_poc",
        "workspace_integration",
        "governance",
    ),
    10: (
        "documents",
        "pathway",
        "nda",
        "workspace_assessment",
        "decisions",
        "workspace_poc",
        "workspace_integration",
        "governance",
        "outcomes",
        "deployments",
        "support",
        "knowledge",
        "meetings",
        "feedback",
    ),
}

# Sections that could name or imply an organisation. identity_state == "anonymous"
# suppresses every one of these, AT ANY STATE (Backend v6.0 §3.1).
ORGANISATION_REVEALING_SECTIONS: frozenset[str] = frozenset(
    {
        "documents",
        "pathway",
        "nda",
        "workspace_assessment",
        "workspace_poc",
        "workspace_integration",
        "decisions",
        "governance",
        "outcomes",
        "deployments",
        "support",
        "knowledge",
        "meetings",
        "feedback",
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# Artifact types (Architecture v2.6 §2.5, mirrored in artifactTypes.ts)
# ─────────────────────────────────────────────────────────────────────────────
ARTIFACT_REFLECTION = "reflection"
ARTIFACT_PITCH_ROOM = "pitch_room"
ARTIFACT_REVIEW_SUMMARY = "review_summary"
ARTIFACT_BOUNDARY_WASTE_MAP = "boundary_waste_map"
ARTIFACT_POC_EVIDENCE = "poc_evidence"
ARTIFACT_INTEGRATION_READINESS = "integration_readiness"
ARTIFACT_SUCCESS_OVERVIEW = "success_overview"
ARTIFACT_DOCUMENT = "document"

ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        ARTIFACT_REFLECTION,
        ARTIFACT_PITCH_ROOM,
        ARTIFACT_REVIEW_SUMMARY,
        ARTIFACT_BOUNDARY_WASTE_MAP,
        ARTIFACT_POC_EVIDENCE,
        ARTIFACT_INTEGRATION_READINESS,
        ARTIFACT_SUCCESS_OVERVIEW,
        ARTIFACT_DOCUMENT,
    }
)

# Which artifact type each state authorizes (Architecture v2.6 §11.1).
ARTIFACTS_BY_STATE: dict[int, tuple[str, ...]] = {
    1: (),
    2: (),
    3: (ARTIFACT_REFLECTION,),
    4: (ARTIFACT_REFLECTION, ARTIFACT_PITCH_ROOM),
    5: (ARTIFACT_REFLECTION, ARTIFACT_PITCH_ROOM, ARTIFACT_REVIEW_SUMMARY),
    6: (
        ARTIFACT_REFLECTION,
        ARTIFACT_PITCH_ROOM,
        ARTIFACT_REVIEW_SUMMARY,
        ARTIFACT_DOCUMENT,
    ),
    7: (
        ARTIFACT_REFLECTION,
        ARTIFACT_PITCH_ROOM,
        ARTIFACT_REVIEW_SUMMARY,
        ARTIFACT_DOCUMENT,
        ARTIFACT_BOUNDARY_WASTE_MAP,
    ),
    8: (
        ARTIFACT_REFLECTION,
        ARTIFACT_PITCH_ROOM,
        ARTIFACT_REVIEW_SUMMARY,
        ARTIFACT_DOCUMENT,
        ARTIFACT_BOUNDARY_WASTE_MAP,
        ARTIFACT_POC_EVIDENCE,
    ),
    9: (
        ARTIFACT_REFLECTION,
        ARTIFACT_PITCH_ROOM,
        ARTIFACT_REVIEW_SUMMARY,
        ARTIFACT_DOCUMENT,
        ARTIFACT_BOUNDARY_WASTE_MAP,
        ARTIFACT_POC_EVIDENCE,
        ARTIFACT_INTEGRATION_READINESS,
    ),
    10: tuple(sorted(ARTIFACT_TYPES)),
}

# ─────────────────────────────────────────────────────────────────────────────
# Disclosure ceilings per state (Architecture v2.6 §11.1)
# ─────────────────────────────────────────────────────────────────────────────
CEILING_PUBLIC = "public"
CEILING_CONTROLLED_PUBLIC = "controlled_public"
CEILING_NDA_ONLY = "nda_only"
CEILING_CUSTOMER_CONTRACT = "customer_contract"
CEILING_INTERNAL = "internal"

# The ceiling a state may reach. The ACTUAL ceiling is min(state ceiling, plane ceiling)
# — the plane always wins (§12.1). This table can never RAISE a plane's ceiling.
STATE_CEILING: dict[int, str] = {
    1: CEILING_PUBLIC,
    2: CEILING_CONTROLLED_PUBLIC,
    3: CEILING_CONTROLLED_PUBLIC,
    4: CEILING_CONTROLLED_PUBLIC,
    5: CEILING_CONTROLLED_PUBLIC,
    6: CEILING_NDA_ONLY,
    7: CEILING_NDA_ONLY,
    8: CEILING_NDA_ONLY,
    9: CEILING_NDA_ONLY,
    10: CEILING_CUSTOMER_CONTRACT,
}

# Ordering used to take the minimum of two ceilings.
CEILING_RANK: dict[str, int] = {
    CEILING_PUBLIC: 0,
    CEILING_CONTROLLED_PUBLIC: 1,
    CEILING_NDA_ONLY: 2,
    CEILING_CUSTOMER_CONTRACT: 3,
    CEILING_INTERNAL: 4,
}


def min_ceiling(a: str, b: str) -> str:
    """Return the more restrictive of two disclosure ceilings."""
    rank_a = CEILING_RANK.get(a, 0)
    rank_b = CEILING_RANK.get(b, 0)
    return a if rank_a <= rank_b else b


# ─────────────────────────────────────────────────────────────────────────────
# identity_state (Architecture v2.6 §10.2)
# ─────────────────────────────────────────────────────────────────────────────
IDENTITY_ANONYMOUS = "anonymous"
IDENTITY_IDENTIFIED = "identified"
IDENTITY_AUTHENTICATED_CUSTOMER = "authenticated_customer"

IDENTITY_STATES: frozenset[str] = frozenset(
    {IDENTITY_ANONYMOUS, IDENTITY_IDENTIFIED, IDENTITY_AUTHENTICATED_CUSTOMER}
)

# ─────────────────────────────────────────────────────────────────────────────
# The ten listening dimensions (Architecture v2.6 §3, coverage tracker in Phase 2)
# ─────────────────────────────────────────────────────────────────────────────
# Declared in Phase 1 so the vocabulary is fixed before the Phase-2 coverage tracker
# consumes it. Phase 1 does not compute coverage; it only reserves the names.
LISTENING_DIMENSIONS: tuple[str, ...] = (
    "workload",
    "platform_environment",
    "pressure_area",
    "scale",
    "baseline",
    "timeline",
    "decision_process",
    "success_definition",
    "constraint",
    "commercial_intent",
)


def journey_number_for(state_key: str) -> int | None:
    """1..10 for a ladder state; None for DORMANT / unknown."""
    return JOURNEY_NUMBERS.get(state_key)


def state_key_for(journey_number: int) -> str | None:
    """state_key for 1..10; None otherwise."""
    return STATE_KEY_BY_NUMBER.get(journey_number)


def validate_sidebar_sections(sections) -> list[str]:
    """
    Assert every key is in the closed vocabulary and return them in canonical order.

    Raises ``ValueError`` on an unknown key — the caller (``shell.py``) turns that into
    a server error. A typo must never degrade silently into a missing section.
    """
    unknown = sorted(set(sections) - SIDEBAR_SECTIONS)
    if unknown:
        raise ValueError(f"Unknown sidebar section key(s): {', '.join(unknown)}")
    wanted = set(sections)
    return [key for key in SIDEBAR_SECTION_ORDER if key in wanted]
