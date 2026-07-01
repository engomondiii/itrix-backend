"""
Agent registry.

A single place that maps an agent key → its class. The runtime and the
``agents/{key}/run/`` endpoint resolve agents through here. The full v4.0 library is the
nine drafting agents plus the Governance meta-agent (final pipeline stage):

    concierge · diagnosis · strategy · pitch · buyer · meeting · objection · proof ·
    proposal    (the nine)   +   governance (the meta-agent)
"""

from __future__ import annotations

from apps.agents.services.base import BaseAgent
from apps.agents.services.buyer import BuyerAgent
from apps.agents.services.concierge import ConciergeAgent
from apps.agents.services.diagnosis import DiagnosisAgent
from apps.agents.services.governance import GovernanceAgent
from apps.agents.services.meeting import MeetingAgent
from apps.agents.services.objection import ObjectionAgent
from apps.agents.services.pitch import PitchAgent
from apps.agents.services.proof import ProofAgent
from apps.agents.services.proposal import ProposalAgent
from apps.agents.services.strategy import StrategyAgent

_REGISTRY: dict[str, type[BaseAgent]] = {
    ConciergeAgent.key: ConciergeAgent,
    DiagnosisAgent.key: DiagnosisAgent,
    StrategyAgent.key: StrategyAgent,
    PitchAgent.key: PitchAgent,
    BuyerAgent.key: BuyerAgent,
    MeetingAgent.key: MeetingAgent,
    ObjectionAgent.key: ObjectionAgent,
    ProofAgent.key: ProofAgent,
    ProposalAgent.key: ProposalAgent,
    GovernanceAgent.key: GovernanceAgent,
}


def register(agent_cls: type[BaseAgent]) -> None:
    _REGISTRY[agent_cls.key] = agent_cls


def get_agent(key: str) -> BaseAgent:
    """Instantiate the agent for ``key``. Raises KeyError if unknown."""
    try:
        return _REGISTRY[key]()
    except KeyError as exc:
        raise KeyError(f"Unknown agent: {key!r}") from exc


def available_keys() -> list[str]:
    return sorted(_REGISTRY.keys())
