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
    context_label: str = "public"  # public | client_page | portal | review | console

    # Free-form extras (conversation id, agent-specific hints).
    extra: dict = field(default_factory=dict)

    @property
    def disclosure_ceiling(self) -> str:
        """The hard retrieval ceiling for this caller's plane + NDA state."""
        if self.plane == PLANE_TEAM:
            return CEILING_INTERNAL
        if self.plane == PLANE_CLIENT:
            return CEILING_NDA if self.nda_signed else CEILING_PUBLIC
        return CEILING_PUBLIC

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
            "pressures": self.pressures,
            "prompt_chars": len(self.prompt or ""),
        }
