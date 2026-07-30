"""
The TWO ZONE VOCABULARIES (Architecture v2.8 §11.6, Backend v7.1 §Phase 1).

v6.0 had one vocabulary — ``SIDEBAR_SECTIONS`` — because the surface had one growing
zone. v7.0 split it in two, and the split is not cosmetic:

    CONVERSATION_RAIL_SECTIONS   THREE keys, and it NEVER GROWS. new_chat,
                                 conversations, account. At every state, on every
                                 plane, in the portal included.

    CONTENT_PANE_SECTIONS        SEVENTEEN keys, and this is the zone that grows.
                                 It is where the WORK is read.

── WHY THE RAIL CANNOT GROW ────────────────────────────────────────────────
In v6.0 the sidebar gained a section per journey state, so by State 10 it carried
fourteen. That made the rail a navigation menu that happened to contain conversations.
The rail's job is to name conversations; everything else moved to the pane.

Three things left the rail entirely and are NOT in either vocabulary below:

    brand_nav    the wordmark is chrome now, not navigation. Approach, Technology and
                 Resources are retired AS NAVIGATION ITEMS on every surface. Their
                 routes stay live and in the sitemap.
    new_review   renamed ``new_chat``. A customer at State 10 opening one is not
                 starting a new review.
    (nothing)    ``explore`` and ``legal`` became PANE sections.

── WHAT THE PANE IS NOT ────────────────────────────────────────────────────
It is not the right value rail that v2.6 retired. Every row that v2.6 §11.6A re-homed
STAYS re-homed, and v2.8 §2.7 restates the re-homing as a prohibition. The pane carries
no next-best-action, no confidentiality notice, no quick help, no specialist card, no
scheduling card and no satisfaction pulse. Those live in the conversation, where the
visitor is — and the reason is not layout preference: they are how a visitor reaches a
human and how they know what not to send us, so they must not live in a panel the
visitor can collapse.

``itrix-web/src/lib/journey/railSections.ts`` and
``itrix-web/src/lib/journey/contentPaneSections.ts`` MIRROR this file. If you change a
key here, change it there in the same PR.

Nothing in this module imports Django models, so it is safe to import from migrations,
management commands, tests and settings.
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# The conversation rail — three keys, forever
# ─────────────────────────────────────────────────────────────────────────────
RAIL_NEW_CHAT = "new_chat"
RAIL_CONVERSATIONS = "conversations"
RAIL_ACCOUNT = "account"

CONVERSATION_RAIL_SECTIONS: tuple[str, ...] = (
    RAIL_NEW_CHAT,
    RAIL_CONVERSATIONS,
    RAIL_ACCOUNT,
)

RAIL_SECTIONS: frozenset[str] = frozenset(CONVERSATION_RAIL_SECTIONS)

# The v6.0 key that has a new name. Everything else in the old vocabulary became a
# pane section, so there is exactly one entry here and there will never be a second.
LEGACY_SIDEBAR_TO_RAIL: dict[str, str] = {
    "new_review": RAIL_NEW_CHAT,
    "conversations": RAIL_CONVERSATIONS,
}

# ─────────────────────────────────────────────────────────────────────────────
# The content pane — seventeen keys, and this is the zone that grows
# ─────────────────────────────────────────────────────────────────────────────
CONTENT_PANE_SECTIONS: tuple[str, ...] = (
    "artifacts",
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

PANE_SECTIONS: frozenset[str] = frozenset(CONTENT_PANE_SECTIONS)

# The canonical render order. The frontend renders in THIS order, not in whatever order
# the payload happens to arrive in.
CONTENT_PANE_SECTION_ORDER: tuple[str, ...] = CONTENT_PANE_SECTIONS

# ── Always present ──────────────────────────────────────────────────────────
# `explore` and `legal` resolve at every state, on every plane. They are ORIENTATION,
# not entitlement — and `legal` in particular is not optional: the four instruments are
# "not permitted to disappear at any width" (§2.4), and the pane is one of only two
# places they live.
BASE_PANE_SECTIONS: tuple[str, ...] = ("explore", "legal")

# ── What each state ADDS on top of the base set (§11.6 growth table) ────────
# States 1-3 add nothing but `artifacts`: the thread itself carries the memory, and the
# only thing worth reading separately is what has been prepared.
CONTENT_PANE_SECTIONS_BY_STATE: dict[int, tuple[str, ...]] = {
    1: (),
    2: ("artifacts",),
    3: ("artifacts",),
    4: ("artifacts", "documents", "pathway"),
    5: ("artifacts", "documents", "pathway"),
    6: ("artifacts", "documents", "pathway", "nda"),
    7: (
        "artifacts", "documents", "pathway", "nda",
        "workspace_assessment", "decisions",
    ),
    8: (
        "artifacts", "documents", "pathway", "nda",
        "workspace_assessment", "decisions", "workspace_poc",
    ),
    9: (
        "artifacts", "documents", "pathway", "nda",
        "workspace_assessment", "decisions", "workspace_poc",
        "workspace_integration", "governance",
    ),
    10: (
        "artifacts", "documents", "pathway", "nda",
        "workspace_assessment", "decisions", "workspace_poc",
        "workspace_integration", "governance",
        "outcomes", "deployments", "support", "knowledge", "meetings", "feedback",
    ),
}

# Pane sections that could name or imply an organisation. ``identity_state ==
# "anonymous"`` suppresses every one of these, AT ANY STATE — the same rule the v6.0
# sidebar had, carried forward unchanged.
#
# `artifacts`, `explore` and `legal` are deliberately absent: an artifact is the
# visitor's own reflection of their own words, and the other two are public.
ORGANISATION_REVEALING_PANE_SECTIONS: frozenset[str] = frozenset(
    {
        "documents", "pathway", "nda",
        "workspace_assessment", "workspace_poc", "workspace_integration",
        "decisions", "governance",
        "outcomes", "deployments", "support", "knowledge", "meetings", "feedback",
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# shell_mode (Architecture v2.8 §2.6)
# ─────────────────────────────────────────────────────────────────────────────
# arrival   one centred column. No rail, no pane, no navigation: the question alone.
# working   rail + conversation column + content pane. Mounted the moment a thread
#           exists, and never unmounted again.
#
# THE MODE IS DERIVED HERE AND RENDERED THERE. A client that decided its own mode could
# render a rail to a visitor the backend has not authorized one for.
SHELL_MODE_ARRIVAL = "arrival"
SHELL_MODE_WORKING = "working"

SHELL_MODES: frozenset[str] = frozenset({SHELL_MODE_ARRIVAL, SHELL_MODE_WORKING})


class UnknownZoneSection(Exception):
    """
    Raised when a section key is not in its closed vocabulary.

    Deliberately an exception rather than a filtered-out key: silently dropping an
    unrecognised section hides a regression instead of surfacing it, and the thing being
    dropped is something a subject was entitled to see.
    """


def validate_rail_sections(sections) -> list[str]:
    """Assert every key is a rail key and return them in canonical order."""
    unknown = sorted(set(sections) - RAIL_SECTIONS)
    if unknown:
        raise UnknownZoneSection(
            f"Unknown conversation-rail section key(s): {', '.join(unknown)}. "
            f"The rail carries {', '.join(CONVERSATION_RAIL_SECTIONS)} only "
            "(Architecture v2.8 §11.6)."
        )
    wanted = set(sections)
    return [key for key in CONVERSATION_RAIL_SECTIONS if key in wanted]


def validate_pane_sections(sections) -> list[str]:
    """Assert every key is a pane key and return them in canonical order."""
    unknown = sorted(set(sections) - PANE_SECTIONS)
    if unknown:
        raise UnknownZoneSection(
            f"Unknown content-pane section key(s): {', '.join(unknown)}."
        )
    wanted = set(sections)
    return [key for key in CONTENT_PANE_SECTION_ORDER if key in wanted]
