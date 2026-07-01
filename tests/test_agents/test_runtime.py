"""Agent runtime: resolves agents, applies governance, records AgentRun."""

from __future__ import annotations

import pytest

from apps.agents.models import AgentRun
from apps.agents.services.context import AgentContext
from apps.agents.services.output_contract import decide_governance
from apps.agents.services.runtime import run_agent, run_diagnosis
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_diagnosis_fallback_returns_empty_and_auto_approves(settings):
    settings.ENABLE_AGENTS = False
    settings.ENABLE_AI_ENGINE = False
    lead = LeadFactory()
    out = run_diagnosis(AgentContext(lead_id=str(lead.id), prompt="slow sim", product_route="alpha_compute"))
    assert out.payload == {}
    assert out.used_ai is False
    assert out.governance_status == "auto_approved"


def test_runtime_records_agent_run(settings):
    settings.ENABLE_AGENTS = False
    lead = LeadFactory()
    run_agent(ctx=AgentContext(lead_id=str(lead.id)), agent_key="diagnosis")
    assert AgentRun.objects.filter(agent_key="diagnosis", lead=lead).exists()


def test_unknown_agent_records_error(settings):
    lead = LeadFactory()
    out = run_agent(ctx=AgentContext(lead_id=str(lead.id)), agent_key="does_not_exist")
    assert out.is_empty()
    run = AgentRun.objects.filter(agent_key="does_not_exist").first()
    assert run is not None and run.status == "error"


def test_governance_threshold(settings):
    settings.AGENT_AUTO_APPROVE_MAX_LEVEL = 2
    assert decide_governance(0) == "auto_approved"
    assert decide_governance(2) == "auto_approved"
    assert decide_governance(3) == "pending"
