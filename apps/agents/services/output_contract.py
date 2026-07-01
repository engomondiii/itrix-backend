"""
Agent output contract + governance outcome.

Every agent returns an ``AgentOutput``: the structured payload, the citations
(chunk ids), whether the AI path was used, and a claim level. The runtime then applies
the governance decision:

    claim_level <= AGENT_AUTO_APPROVE_MAX_LEVEL  → auto_approved (delivered)
    else                                         → pending (queued for human approval)

In Phase 1 the Diagnosis agent produces claim_level 0–2 content (qualitative, within
the claims discipline), so it auto-approves and the result page renders exactly as
before. The queue/approval machinery is fully wired in Phase 3; here we compute and
record the governance_status so the contract is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings

GOV_AUTO_APPROVED = "auto_approved"
GOV_PENDING = "pending"
GOV_BLOCKED = "blocked"


@dataclass
class AgentOutput:
    payload: dict = field(default_factory=dict)
    chunk_ids: list[str] = field(default_factory=list)
    used_ai: bool = False
    claim_level: int = 0
    # Set by the runtime after the governance decision.
    governance_status: str = GOV_AUTO_APPROVED

    def is_empty(self) -> bool:
        return not self.payload


def decide_governance(claim_level: int) -> str:
    """Auto-approve at/below the configured threshold; otherwise queue for review."""
    threshold = int(getattr(settings, "AGENT_AUTO_APPROVE_MAX_LEVEL", 2))
    if claim_level <= threshold:
        return GOV_AUTO_APPROVED
    return GOV_PENDING
