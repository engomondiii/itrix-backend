"""
SECURITY INVARIANT 2 — the plane sets the ceiling (Backend v6.0 §Phase 1, §19.6).

The shipped build had two ways to widen retrieval beyond what the caller's identity
plane allowed:

1. Several agents passed a LITERAL ``context="internal"`` to the retriever.
2. Others derived the context from ``context_label`` — a DISPLAY label. An anonymous
   visitor holding a client_page capability token has ``context_label == "client_page"``
   while still being on the PUBLIC plane, so ``nda_signed`` plus that label granted
   nda-tier retrieval to an unidentified visitor.

``AgentContext.retrieval_context`` is now the single derived value, and these tests pin
both the mapping and the absence of literals.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from apps.agents.services.context import (
    PLANE_CLIENT,
    PLANE_PUBLIC,
    PLANE_TEAM,
    AgentContext,
)

AGENTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "apps" / "agents" / "services"


def test_public_plane_maps_to_public_retrieval():
    ctx = AgentContext(plane=PLANE_PUBLIC)
    assert ctx.retrieval_context == "public"


def test_public_plane_stays_public_even_with_a_client_page_label():
    """
    THE REGRESSION. A display label must never widen the ceiling.

    An anonymous visitor holding a client_page token looks like a client to any code
    that reads context_label. It is not one.
    """
    ctx = AgentContext(plane=PLANE_PUBLIC, context_label="client_page", nda_signed=True)
    assert ctx.retrieval_context == "public"


def test_client_plane_without_nda_is_controlled():
    ctx = AgentContext(plane=PLANE_CLIENT, nda_signed=False)
    assert ctx.retrieval_context == "controlled"


def test_client_plane_with_nda_is_nda():
    ctx = AgentContext(plane=PLANE_CLIENT, nda_signed=True)
    assert ctx.retrieval_context == "nda"


def test_client_plane_with_contract_is_customer_contract():
    ctx = AgentContext(plane=PLANE_CLIENT, nda_signed=True, contract_executed=True)
    assert ctx.retrieval_context == "customer_contract"


def test_team_plane_is_internal():
    ctx = AgentContext(plane=PLANE_TEAM)
    assert ctx.retrieval_context == "internal"


def test_no_agent_passes_a_literal_retrieval_context():
    """
    A static assertion over the agent sources.

    Written as a source scan rather than a behavioural test on purpose: the failure mode
    is a NEW agent added later with a copied-in literal, and only a scan catches that.
    """
    literal = re.compile(r'context\s*=\s*["\'](?:internal|nda|customer_contract)["\']')
    offenders = []
    for path in sorted(AGENTS_DIR.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # the fix banner quotes the old literal
            if literal.search(line):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "agents must pass ctx.retrieval_context, not a literal:\n" + "\n".join(offenders)


def test_retrieval_context_appears_in_the_digest():
    """The cockpit must be able to see which ceiling actually applied."""
    ctx = AgentContext(plane=PLANE_CLIENT, nda_signed=True)
    assert ctx.digest()["retrieval_context"] == "nda"
