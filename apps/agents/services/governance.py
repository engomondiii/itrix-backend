"""
Governance meta-agent (Backend v4 §2.2, §6) — the FINAL pipeline stage.

Not user-invokable and not optional: the runtime runs this over every agent's output and
every team→client message before delivery. Low-risk conversational text stays non-blocking,
but a failure inside a safety control discards the original generated text and substitutes
fixed approved copy. Availability is preserved without converting a control failure into
implicit approval.
"""

from __future__ import annotations

import logging

from apps.agents.services.base import BaseAgent
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import (
    GOV_AUTO_APPROVED,
    GOV_BLOCKED,
    GOV_PENDING,
    AgentOutput,
)
from apps.core.safe_responses import governance_unavailable

logger = logging.getLogger("itrix")

_NON_BLOCKING_CONVERSATION_CONTEXTS = frozenset({
    "anonymous_review",
    "review",
    "client_page",
    "portal",
})


def is_non_blocking_conversation_context(context: str, *, claim_level: int = 1) -> bool:
    """True only for low-risk Concierge-style visitor/client conversation text."""
    try:
        level = int(claim_level)
    except (TypeError, ValueError):
        level = 99
    return level <= 1 and str(context or "").strip().lower() in _NON_BLOCKING_CONVERSATION_CONTEXTS


def _scrub_non_blocking_conversation(text: str, *, locale: str = "en") -> tuple[str, bool]:
    """Scrub low-risk chat; return fixed safe text if the scrubber itself fails.

    The boolean tells ``govern_text`` whether the fixed fallback was used so the audit
    reason is explicit. The original model output is never returned from the exception
    path.
    """
    original = text or ""
    try:
        import re
        from apps.ai_engine.services import prohibited_language_checker as plc

        out = plc.scrub(original)
        replacement = "a workload-specific measured advantage, subject to validation"
        for pattern in plc.HARD_BLOCK_PATTERNS:
            out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
        return out, False
    except Exception:  # noqa: BLE001 - content safety fails closed, conversation stays usable
        logger.exception("conversation scrub failed; substituting approved safe fallback")
        return governance_unavailable(locale=locale), True


def govern_text(
    text: str,
    *,
    claim_level: int = 1,
    context: str = "public",
    locale: str = "en",
) -> dict:
    """Govern one piece of outbound text. Never raises and never fail-opens content."""
    if is_non_blocking_conversation_context(context, claim_level=claim_level):
        governed, fallback_used = _scrub_non_blocking_conversation(text, locale=locale)
        return {
            "status": GOV_AUTO_APPROVED,
            "text": governed,
            "claim_level": int(claim_level or 1),
            "requires_second_approver": False,
            "violations": ["governance_unavailable"] if fallback_used else [],
            "reason": (
                "governance_error_safe_fallback"
                if fallback_used
                else "non_blocking_conversation"
            ),
        }

    try:
        from apps.governance.services.claim_checker import check

        decision = check(text, claim_level=claim_level, context=context)
        return {
            "status": decision.status,
            "text": decision.text,
            "claim_level": decision.claim_level,
            "requires_second_approver": decision.requires_second_approver,
            "violations": decision.violations,
            "reason": decision.reason,
        }
    except Exception:  # noqa: BLE001 - never deliver original after governance failure
        logger.exception("Governance check failed; substituting approved safe fallback")
        return {
            "status": GOV_AUTO_APPROVED,
            "text": governance_unavailable(locale=locale),
            "claim_level": int(claim_level or 1),
            "requires_second_approver": False,
            "violations": ["governance_unavailable"],
            "reason": "governance_error_safe_fallback",
        }


class GovernanceAgent(BaseAgent):
    key = "governance"
    name = "Governance agent"
    default_claim_level = 0

    def run_ai(self, ctx: AgentContext) -> AgentOutput:
        return self.run_fallback(ctx)

    def run_fallback(self, ctx: AgentContext) -> AgentOutput:
        text = (ctx.extra or {}).get("text", "") or ctx.prompt
        claim_level = int((ctx.extra or {}).get("claim_level", 1))
        locale = str((ctx.extra or {}).get("locale", "en") or "en")
        decision = govern_text(
            text,
            claim_level=claim_level,
            context=ctx.context_label,
            locale=locale,
        )
        return AgentOutput(
            payload=decision,
            used_ai=False,
            claim_level=claim_level,
            governance_status=decision["status"],
        )
