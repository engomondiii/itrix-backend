"""
Agent context.

``AgentContext`` is the immutable input an agent runs against: the subject (lead +
optional client), the caller's identity plane and disclosure ceiling, the visitor's
prompt + pressures, product/license routing, tier, and the conversation/context label
(public | client_page | portal | review | console). The runtime builds this once and
passes it to the agent, so agents never reach into Django models ad hoc.

The plane + NDA state become the HARD disclosure ceiling handed to the retriever
(Backend v4 §3.1) — no prompt can raise it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Disclosure ceilings per plane (the retriever enforces these as a hard cap).
PLANE_PUBLIC = "public"
PLANE_CLIENT = "client"
PLANE_TEAM = "team"

CEILING_PUBLIC = "controlled_public"
CEILING_NDA = "nda_only"
CEILING_INTERNAL = "internal_only"

# ─────────────────────────────────────────────────────────────────────────────
# SECURITY INVARIANT 2 — THE PLANE SETS THE CEILING
# ─────────────────────────────────────────────────────────────────────────────
# Backend v6.0 §Phase 1 / Architecture v2.6 §12.1, restated because it was VIOLATED in
# the shipped build: several agents passed a literal ``context="internal"`` to the
# retriever, which meant an anonymous visitor's question could be answered from
# internal_only chunks.
#
# ``retrieval_context`` is the ONE derived value every agent must use. No agent may pass
# a literal. The mapping is fixed:
#
#     team plane                 -> internal
#     client plane + contract    -> customer_contract
#     client plane + nda         -> nda
#     anything else              -> public
#
# ``disclosure_ceiling`` is RETAINED alongside it for audit — it is what gets logged and
# shown in the cockpit — but it is the retrieval_context that actually gates retrieval.
RETRIEVAL_PUBLIC = "public"
RETRIEVAL_CONTROLLED = "controlled"
RETRIEVAL_NDA = "nda"
RETRIEVAL_CUSTOMER_CONTRACT = "customer_contract"
RETRIEVAL_INTERNAL = "internal"


@dataclass(frozen=True)
class AgentContext:
    # Subject
    lead_id: str | None = None
    client_id: str | None = None

    # Problem framing
    prompt: str = ""
    pressures: list[str] = field(default_factory=list)
    product_route: str = "general"
    license_pathway: str | None = None
    tier: int = 4

    # Identity plane + disclosure
    plane: str = PLANE_PUBLIC
    nda_signed: bool = False
    contract_executed: bool = False
    context_label: str = "public"  # public | client_page | portal | review | console

    # Free-form extras (conversation id, agent-specific hints).
    extra: dict = field(default_factory=dict)

    @property
    def disclosure_ceiling(self) -> str:
        """
        The hard disclosure ceiling for this caller's plane + NDA state.

        Retained for AUDIT and cockpit display. Retrieval itself is gated by
        ``retrieval_context`` below — the two must never be allowed to disagree, which
        is why both are derived from the same plane rather than set independently.
        """
        if self.plane == PLANE_TEAM:
            return CEILING_INTERNAL
        if self.plane == PLANE_CLIENT:
            return CEILING_NDA if self.nda_signed else CEILING_PUBLIC
        return CEILING_PUBLIC

    @property
    def retrieval_context(self) -> str:
        """
        The retrieval context key — SECURITY INVARIANT 2.

        Derived from the identity plane and the NDA/contract state, and from NOTHING
        else. Not from the prompt, not from an attachment, not from the journey state,
        and never from an agent's own opinion about what it needs.

        Every agent passes ``ctx.retrieval_context`` to the retriever. A literal in an
        agent is a defect with a named regression test
        (``tests/test_agents/test_retrieval_ceiling.py``).
        """
        if self.plane == PLANE_TEAM:
            return RETRIEVAL_INTERNAL
        if self.plane == PLANE_CLIENT:
            if self.contract_executed:
                return RETRIEVAL_CUSTOMER_CONTRACT
            if self.nda_signed:
                return RETRIEVAL_NDA
            return RETRIEVAL_CONTROLLED
        return RETRIEVAL_PUBLIC

    @classmethod
    def from_lead(cls, lead, *, context_label: str = "public", plane: str = PLANE_PUBLIC) -> "AgentContext":
        session = getattr(lead, "review_session", None)
        return cls(
            lead_id=str(lead.id),
            client_id=str(getattr(lead, "client_id", "") or ""),
            prompt=getattr(session, "prompt", "") or "",
            pressures=list(getattr(session, "pressure_areas", []) or []),
            product_route=getattr(lead, "product_route", "general"),
            license_pathway=(
                lead.commercial_path if getattr(lead, "commercial_path", "none") != "none" else None
            ),
            tier=getattr(lead, "tier", 4),
            plane=plane,
            context_label=context_label,
        )

    def digest(self) -> dict:
        """A compact, loggable summary of the input (no PII beyond ids)."""
        return {
            "lead_id": self.lead_id,
            "client_id": self.client_id or None,
            "product_route": self.product_route,
            "license_pathway": self.license_pathway,
            "tier": self.tier,
            "plane": self.plane,
            "context_label": self.context_label,
            "ceiling": self.disclosure_ceiling,
            "retrieval_context": self.retrieval_context,
            "pressures": self.pressures,
            "prompt_chars": len(self.prompt or ""),
        }
