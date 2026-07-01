"""
BaseAgent — the contract every agent implements.

An agent takes an ``AgentContext`` and returns an ``AgentOutput``. Subclasses implement
``run_ai`` (the Claude-backed path) and ``run_fallback`` (the deterministic path). The
base ``run`` wraps them: it tries the AI path only when ``ENABLE_AGENTS`` +
``ENABLE_AI_ENGINE`` are on and a key is present, and ALWAYS falls back to the
deterministic path on any failure — preserving the shipped result page's graceful
degradation verbatim. The runtime (not the agent) records the AgentRun + governance.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import AgentOutput

logger = logging.getLogger("itrix")


class BaseAgent:
    #: stable key used in the registry, AgentRun, and the run endpoint
    key: str = "base"
    #: human label
    name: str = "Base agent"
    #: default claim level of this agent's output (governs auto-approve)
    default_claim_level: int = 0

    def run_ai(self, ctx: AgentContext) -> AgentOutput:  # pragma: no cover - abstract
        raise NotImplementedError

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:  # pragma: no cover - abstract
        raise NotImplementedError

    # ── orchestration ────────────────────────────────────────────────────────
    @property
    def ai_enabled(self) -> bool:
        return bool(
            getattr(settings, "ENABLE_AGENTS", False)
            and getattr(settings, "ENABLE_AI_ENGINE", False)
            and getattr(settings, "ANTHROPIC_API_KEY", "")
        )

    def run(self, ctx: AgentContext) -> AgentOutput:
        """Try AI (when enabled), else deterministic; never raise for callers."""
        if self.ai_enabled:
            try:
                out = self.run_ai(ctx)
                if out and not out.is_empty():
                    return out
                logger.debug("Agent %s AI path returned empty; using fallback", self.key)
            except Exception:  # noqa: BLE001
                logger.exception("Agent %s AI path failed; using fallback", self.key)
        return self.run_fallback(ctx)
