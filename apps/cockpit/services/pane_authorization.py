"""
CONTENT-PANE AUTHORIZATION (Architecture v2.8 §11.6, Backend v7.1 Phase 2).

Phase 1 authorized the pane's SECTION LIST. This authorizes its CONTENTS.

── THE DIFFERENCE, AND WHY BOTH ARE NEEDED ─────────────────────────────────

Phase 1's ``content_pane_sections`` says *which tabs a subject may see*. It is a list of
seventeen possible strings, and it is enough to stop a visitor at State 2 from seeing an
``outcomes`` tab.

It is not enough to stop that visitor from reading a State 10 artifact whose id they
guessed, because the artifact read is a different request. So this module answers the
second question: for THIS subject, on THIS plane, which artifacts and documents may the
pane actually render?

── THREE RULES, IN ORDER OF HOW BADLY THEY FAIL ────────────────────────────

1. GOVERNANCE FIRST. An artifact that is not ``approved`` does not appear, whatever its
   disclosure level and whatever section asked for it. Under review means a human has not
   finished deciding, and the pane is not the place that decision gets pre-empted.

2. THE CEILING NEXT. An artifact's ``disclosure_level`` must be at or below the subject's
   effective ceiling — which is itself the more restrictive of the plane's cap and the
   state's (§12.1). The plane always wins.

3. THE SECTION LAST. An artifact only appears if the section that would render it is in the
   subject's authorized list. This is the weakest of the three and it is deliberately last:
   it is a presentation concern, and if the first two are satisfied the content is already
   safe to show.

Ordering them this way means a bug in the section mapping produces a MISSING artifact, not
a leaked one.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("itrix")

# Which artifact types belong to which pane section. Mirrors
# itrix-web/src/components/content-pane/sections/. A type with no section here is
# unreachable through the pane, which is the safe default for a type nobody has designed a
# section for yet.
SECTION_ARTIFACT_TYPES: dict[str, tuple[str, ...]] = {
    "artifacts": (
        "reflection", "pitch_room", "review_summary",
        "boundary_waste_map", "poc_evidence", "integration_readiness",
    ),
    "documents": ("document",),
    "workspace_assessment": ("boundary_waste_map",),
    "workspace_poc": ("poc_evidence",),
    "workspace_integration": ("integration_readiness",),
}

# Ceiling ordering, loosest first. Imported rather than restated where possible; kept here
# as a fallback so this module can be reasoned about on its own.
_CEILING_RANK = {
    "public": 0,
    "controlled_public": 1,
    "nda_only": 2,
    "customer_contract": 3,
    "internal": 4,
}


def _within_ceiling(level: str, ceiling: str) -> bool:
    """True when ``level`` is at or below ``ceiling``. Unknown levels are refused."""
    if level not in _CEILING_RANK or ceiling not in _CEILING_RANK:
        # An unrecognised level is refused rather than passed through. A new level added
        # server-side should become invisible here until someone decides where it sits —
        # the alternative is that it becomes visible to everyone.
        logger.warning("pane_authorization: unknown level=%r ceiling=%r; refusing", level, ceiling)
        return False
    return _CEILING_RANK[level] <= _CEILING_RANK[ceiling]


def authorized_artifacts(thread, *, disclosure_ceiling: str, sections) -> list[dict]:
    """
    The artifacts this subject's pane may render, newest first.

    Returns the payload the pane needs and nothing more. In particular it does NOT return
    ``capability_token``: a token is a bearer credential for a deep link, and the pane
    renders in place. Including one would put a credential in a payload that has no use
    for it — which is how credentials end up in logs.
    """
    from apps.journey.models_artifacts import Artifact

    if thread is None:
        return []

    allowed_sections = set(sections or ())
    allowed_types: set[str] = set()
    for section in allowed_sections:
        allowed_types.update(SECTION_ARTIFACT_TYPES.get(section, ()))

    if not allowed_types:
        return []

    out: list[dict] = []
    qs = Artifact.objects.filter(thread_id=thread.id).order_by("-created_at", "-version")

    for art in qs[:200]:
        # RULE 1 — governance first.
        if art.governance_status != "approved":
            continue
        # RULE 2 — the ceiling next.
        if not _within_ceiling(art.disclosure_level or "internal", disclosure_ceiling):
            continue
        # RULE 3 — the section last.
        if art.type not in allowed_types:
            continue

        out.append(
            {
                "id": str(art.id),
                "type": art.type,
                "version": art.version,
                "payload": art.payload or {},
                "disclosureLevel": art.disclosure_level,
                "governanceStatus": art.governance_status,
                "pinned": bool(art.pinned),
                "createdAt": art.created_at.isoformat(),
            }
        )
    return out


def default_artifact_id(artifacts) -> str | None:
    """
    Which artifact the pane opens on.

    The newest non-pinned one. Pinned artifacts — ``success_overview`` — are standing
    context above the transcript, so opening the pane onto one would show the same thing
    twice.
    """
    for art in artifacts or ():
        if not art.get("pinned"):
            return art["id"]
    return None
