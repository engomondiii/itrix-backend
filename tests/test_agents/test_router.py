"""Agent router + registry."""

from __future__ import annotations

from apps.agents.services.registry import available_keys, get_agent
from apps.agents.services.router import agent_key_for_context


def test_registry_has_the_two_phase1_agents():
    keys = available_keys()
    assert "concierge" in keys
    assert "diagnosis" in keys


def test_get_agent_returns_instance():
    assert get_agent("diagnosis").key == "diagnosis"
    assert get_agent("concierge").key == "concierge"


def test_router_maps_contexts():
    assert agent_key_for_context("review") == "concierge"
    assert agent_key_for_context("client_page") == "concierge"
    assert agent_key_for_context("result_page") == "diagnosis"
    # unknown → diagnosis default
    assert agent_key_for_context("whatever") == "diagnosis"
