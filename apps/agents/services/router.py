"""
Agent router.

Given a context label, decide which agent should handle it. This keeps callers from
hard-coding agent keys: the review/client-page/portal chat routes to the Concierge; the
result page routes to the Diagnosis agent; the pitch room routes to the Pitch agent.
"""

from __future__ import annotations

from apps.agents.services.concierge import ConciergeAgent
from apps.agents.services.diagnosis import DiagnosisAgent
from apps.agents.services.pitch import PitchAgent

# context_label → agent key
_CONTEXT_TO_AGENT = {
    "review": ConciergeAgent.key,
    "client_page": ConciergeAgent.key,
    "portal": ConciergeAgent.key,
    "result_page": DiagnosisAgent.key,
    "diagnosis": DiagnosisAgent.key,
    "pitch": PitchAgent.key,
}


def agent_key_for_context(context_label: str) -> str:
    return _CONTEXT_TO_AGENT.get(context_label, DiagnosisAgent.key)
