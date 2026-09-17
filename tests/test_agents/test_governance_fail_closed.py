from __future__ import annotations

from types import SimpleNamespace

from apps.agents.services import governance
from apps.conversations.services import response_policy
from apps.core.safe_responses import governance_unavailable


RISKY = "We guarantee 100x performance. You should start ALPHA Compute immediately."


def test_non_blocking_scrubber_exception_never_returns_original(monkeypatch, caplog):
    def explode(_text):
        raise RuntimeError("sensitive implementation detail")

    monkeypatch.setattr(
        "apps.ai_engine.services.prohibited_language_checker.scrub",
        explode,
    )

    decision = governance.govern_text(
        RISKY,
        claim_level=1,
        context="anonymous_review",
        locale="en",
    )

    assert decision["text"] == governance_unavailable(locale="en")
    assert RISKY not in decision["text"]
    assert "100x" not in decision["text"]
    assert decision["reason"] == "governance_error_safe_fallback"
    assert "conversation scrub failed" in caplog.text
    assert "sensitive implementation detail" not in decision["text"]


def test_recommendation_gate_exception_never_removes_restriction(monkeypatch, caplog):
    thread = SimpleNamespace(
        locale="en",
        contract_stage="no_discussion",
        relationship_state="customer",
    )
    monkeypatch.setattr(
        "apps.conversations.services.engagement_state.is_customer",
        lambda _thread: True,
    )

    def explode(_thread):
        raise RuntimeError("policy database detail")

    monkeypatch.setattr(
        "apps.conversations.services.engagement_state.recommendation_allowed",
        explode,
    )

    governed = response_policy.enforce(RISKY, thread=thread)
    assert governed == governance_unavailable(locale="en")
    assert RISKY not in governed
    assert "ALPHA Compute immediately" not in governed
    assert "recommendation policy failed" in caplog.text
    assert "policy database detail" not in governed
