"""
Agent runtime.

The one orchestrator that:
    1. resolves the agent (by key or by context label via the router),
    2. runs it against an AgentContext (AI path when enabled, deterministic otherwise),
    3. applies the governance decision (auto-approve ≤ AGENT_AUTO_APPROVE_MAX_LEVEL,
       else pending),
    4. records an ``AgentRun`` audit row (best-effort),
    5. returns the ``AgentOutput`` with its final governance_status.

Callers (qualification_processor, result_generator, the run endpoint, the Phase 3 chat
consumers) go through here so governance + audit are applied uniformly and centrally.
Nothing here raises for the happy path — a failed agent degrades to a deterministic
fallback and an ``error`` AgentRun.
"""

from __future__ import annotations

import logging
import time

from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import AgentOutput, decide_governance
from apps.agents.services.registry import get_agent
from apps.agents.services.router import agent_key_for_context

logger = logging.getLogger("itrix")


def run_agent(
    *,
    ctx: AgentContext,
    agent_key: str | None = None,
    context_label: str | None = None,
    record: bool = True,
) -> AgentOutput:
    """Run an agent (resolved by key or context label) with governance + audit."""
    key = agent_key or agent_key_for_context(context_label or ctx.context_label)

    started = time.monotonic()
    status = "ok"
    error = ""
    try:
        agent = get_agent(key)
        output = agent.run(ctx)
    except Exception as exc:  # noqa: BLE001 - runtime must never propagate
        logger.exception("Agent runtime failed for key=%s", key)
        output = AgentOutput(payload={}, used_ai=False, claim_level=0)
        status = "error"
        error = str(exc)

    # ── Final pipeline stage: GOVERNANCE ─────────────────────────────────────
    # Every outbound agent output passes the Governance meta-agent. Its textual content
    # is scrubbed + checked; the claim level decides auto-approve vs. queue-for-human.
    # (decide_governance remains the fast path when there is no text to govern.)
    _apply_governance(key, ctx, output)

    if status == "ok" and not output.used_ai and output.is_empty():
        status = "fallback"

    duration_ms = int((time.monotonic() - started) * 1000)

    if record:
        _record_run(key, ctx, output, status=status, error=error, duration_ms=duration_ms)

    return output


# ── governance helpers ───────────────────────────────────────────────────────
def _extract_text(payload: dict) -> str:
    """Pull the human-facing text from an agent payload for the governance pass."""
    if not isinstance(payload, dict):
        return ""
    for k in ("reply", "text", "headline", "body"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _apply_governance(agent_key: str, ctx: AgentContext, output: AgentOutput) -> None:
    """
    Govern the output: run the Governance meta-agent over its text, set the final
    governance_status, and queue an ApprovalRequest when it is not auto-approved.
    Best-effort — falls back to the claim-level threshold if governance is unavailable.
    """
    text = _extract_text(output.payload)
    try:
        from apps.agents.services.governance import govern_text

        decision = govern_text(text, claim_level=output.claim_level, context=ctx.context_label)
        output.governance_status = decision["status"]
        # If governance scrubbed the text, reflect it back into the common text fields.
        if text and decision.get("text") and decision["text"] != text:
            for k in ("reply", "text", "headline", "body"):
                if isinstance(output.payload.get(k), str) and output.payload[k] == text:
                    output.payload[k] = decision["text"]
                    break
        if decision["status"] != "auto_approved":
            _queue_output(agent_key, ctx, output)
    except Exception:  # noqa: BLE001
        logger.exception("governance pass failed; falling back to threshold decision")
        output.governance_status = decide_governance(output.claim_level)


def _queue_output(agent_key: str, ctx: AgentContext, output: AgentOutput) -> None:
    """Write an ApprovalRequest for a non-auto-approved agent output (best-effort)."""
    try:
        from apps.governance.services.approval_router import queue_for_approval
        from apps.leads.models import Lead

        lead = Lead.objects.filter(id=ctx.lead_id).first() if ctx.lead_id else None
        queue_for_approval(
            message_id="",  # standalone agent run (not a conversation message)
            conversation_id="",
            lead=lead,
            client_id=ctx.client_id or "",
            agent_key=agent_key,
            claim_level=output.claim_level,
            draft_body=_extract_text(output.payload),
            cited_chunk_ids=output.chunk_ids,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to queue approval for agent %s", agent_key)


def _record_run(key, ctx, output, *, status, error, duration_ms) -> None:
    try:
        from apps.agents.models import AgentRun

        lead = None
        if ctx.lead_id:
            from apps.leads.models import Lead

            lead = Lead.objects.filter(id=ctx.lead_id).first()

        AgentRun.objects.create(
            agent_key=key,
            lead=lead,
            client_id=ctx.client_id or "",
            status=status,
            used_ai=output.used_ai,
            governance_status=output.governance_status,
            claim_level=output.claim_level,
            input_summary=ctx.digest(),
            output=output.payload,
            chunk_ids=output.chunk_ids,
            error=error,
            duration_ms=duration_ms,
        )
    except Exception:  # noqa: BLE001 - audit is best-effort
        logger.exception("Failed to record AgentRun for key=%s", key)


# ── Convenience wrappers for the two Phase 1 agents ──────────────────────────
def run_diagnosis(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="diagnosis")


def run_concierge(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="concierge")


def run_pitch(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="pitch")


def run_strategy(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="strategy")


def run_buyer(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="buyer")


def run_meeting(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="meeting")


def run_objection(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="objection")


def run_proof(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="proof")


def run_proposal(ctx: AgentContext) -> AgentOutput:
    return run_agent(ctx=ctx, agent_key="proposal")
