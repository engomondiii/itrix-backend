"""Operator endpoints: agent-run audit list + cockpit richer visitor-read."""

from __future__ import annotations

import pytest

from apps.agents.services.context import AgentContext
from apps.agents.services.runtime import run_agent
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_agent_runs_endpoint_lists_records(auth_client, settings):
    settings.ENABLE_AGENTS = False
    lead = LeadFactory()
    run_agent(ctx=AgentContext(lead_id=str(lead.id)), agent_key="diagnosis")

    r = auth_client.get("/api/v1/agents/runs/")
    assert r.status_code == 200
    assert isinstance(r.data, list)
    assert len(r.data) >= 1
    assert {"agentKey", "governanceStatus", "claimLevel", "at"} <= set(r.data[0].keys())


def test_agent_runs_requires_auth(api_client):
    r = api_client.get("/api/v1/agents/runs/")
    assert r.status_code in (401, 403)


def test_cockpit_returns_richer_read(auth_client):
    lead = LeadFactory(score=88)

    r = auth_client.get(f"/api/v1/cockpit/leads/{lead.id}/")
    assert r.status_code == 200
    data = r.data

    # base fields still present
    assert data["leadId"] == str(lead.id)
    assert "pitchEngagement" in data

    # richer internal read
    for key in (
        "visitorType",
        "buyerPsychology",
        "readiness",
        "licenseOutProbability",
        "ladderStage",
    ):
        assert key in data
    assert set(data["readiness"].keys()) == {"nda", "assessment", "poc"}
    assert 0 <= data["licenseOutProbability"] <= 100


def test_cockpit_next_action(auth_client):
    lead = LeadFactory()

    r = auth_client.get(f"/api/v1/cockpit/leads/{lead.id}/next-action/")
    assert r.status_code == 200
    assert "nextAction" in r.data and "reason" in r.data
