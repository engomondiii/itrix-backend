"""
Celery tasks for the agent runtime.

Thin wrappers so agent runs can be offloaded (result-page enrichment, ad-hoc runs).
Eager when ``ENABLE_CELERY`` is False (the default), so ``.delay()`` executes
synchronously in-process — the whole system works with no broker running.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("itrix")


@shared_task(name="agents.run_agent_for_lead")
def run_agent_for_lead_task(agent_key: str, lead_id: str, *, context_label: str = "diagnosis") -> dict:
    """Run an agent against a lead through the runtime (records an AgentRun)."""
    from apps.agents.services.context import AgentContext
    from apps.agents.services.runtime import run_agent
    from apps.leads.models import Lead

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}

    ctx = AgentContext.from_lead(lead, context_label=context_label)
    output = run_agent(ctx=ctx, agent_key=agent_key)
    return {
        "ok": True,
        "lead_id": str(lead.id),
        "agent_key": agent_key,
        "used_ai": output.used_ai,
        "governance_status": output.governance_status,
    }


@shared_task(name="agents.rerun_diagnosis")
def rerun_diagnosis_task(lead_id: str) -> dict:
    """Re-run the Diagnosis agent + regenerate the result page for a lead."""
    from apps.leads.models import Lead
    from apps.result_page.services.result_generator import ResultGenerator

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}
    result_obj, report = ResultGenerator().generate_for_lead(lead)
    return {"ok": True, "lead_id": str(lead.id), "result_page_id": str(result_obj.id), **report}


@shared_task(name="agents.draft_heavy")
def draft_heavy_task(agent_key: str, lead_id: str, *, document_type: str = "evaluation") -> dict:
    """
    Run a HEAVY drafting agent (Proposal, Proof) asynchronously. These are L3/L5 by
    default, so the runtime governs the output and — because it exceeds the auto-approve
    threshold — queues an ApprovalRequest on completion. Eager when ENABLE_CELERY is off.
    """
    from apps.agents.services.context import AgentContext, PLANE_TEAM
    from apps.agents.services.runtime import run_agent
    from apps.leads.models import Lead

    lead = Lead.objects.filter(pk=lead_id).first()
    if not lead:
        return {"ok": False, "error": f"No lead {lead_id}"}

    ctx = AgentContext.from_lead(lead, context_label="console", plane=PLANE_TEAM)
    ctx = AgentContext(**{**ctx.__dict__, "extra": {**ctx.extra, "document_type": document_type}})
    output = run_agent(ctx=ctx, agent_key=agent_key)
    # governance_status is set by the runtime; a non-auto status means it was queued.
    return {
        "ok": True,
        "lead_id": str(lead.id),
        "agent_key": agent_key,
        "governance_status": output.governance_status,
        "queued_for_approval": output.governance_status != "auto_approved",
    }
