"""
Support routing (Playbook §12D, Backend v6.0 §Phase 2).

    NEVER SELL INTO A SUPPORT THREAD. A support reply helps with the problem and stops.
    It does not mention another workload, an expansion, a renewal, or a next agreement —
    NO MATTER HOW NATURAL THE SEGUE SEEMS.
"""

from __future__ import annotations

import pytest

from apps.customer_success.models import SupportRequest
from apps.customer_success.services import support_router

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("text", [
    "The deployment is not working since the last update",
    "We are getting an error on every run",
    "Production is down",
    "I need help with the integration",
    "This is broken and we are blocked",
])
def test_support_intent_is_detected(text):
    assert support_router.detect_support_intent(text) is True


@pytest.mark.parametrize("text", [
    "What would an assessment involve?",
    "Can you tell me more about ALPHA Core?",
    "We are considering a licence for another team",
])
def test_ordinary_questions_are_not_support(text):
    assert support_router.detect_support_intent(text) is False


def test_detection_is_deterministic_not_a_model_call():
    """
    Layer 1 stays LLM-free. If a model decided what counted as support, a model would be
    deciding when the commercial-suppression rule applies.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(support_router))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for module in imported:
        lowered = module.lower()
        for forbidden in ("claude", "openai", "anthropic", "ai_engine"):
            assert forbidden not in lowered


def test_production_outage_is_critical_and_blocking(paying_client):
    request = support_router.route(paying_client, "Production is down, we cannot run at all")
    assert request.urgency == SupportRequest.Urgency.CRITICAL
    assert request.blocking is True


def test_a_routine_question_is_not_blocking(paying_client):
    request = support_router.route(paying_client, "The docs seem out of date for one flag")
    assert request.blocking is False


def test_the_request_gets_an_owner_and_an_sla(paying_client):
    from apps.customer_success.services import overlay

    overlay.activate(paying_client)
    request = support_router.route(paying_client, "Something is not working")
    assert request.owner_name
    assert request.sla_due_at is not None


def test_the_acknowledgement_names_the_owner_and_the_sla(paying_client):
    """
    'We have this. {owner} owns it and will respond within {sla}.' — only possible if
    both are resolved at creation. An SLA nobody is tracking is worse than none.
    """
    from apps.customer_success.services import overlay

    overlay.activate(paying_client)
    request = support_router.route(paying_client, "It is broken")
    copy = support_router.acknowledge_copy(request)
    assert request.owner_name in copy
    assert "hours" in copy


def test_a_blocking_request_is_visible_to_the_nba_rule(paying_client):
    support_router.route(paying_client, "We are completely blocked in production")
    assert support_router.open_blocking_for(paying_client) is True


def test_resolving_clears_the_blocking_signal(paying_client):
    request = support_router.route(paying_client, "We are blocked in production")
    support_router.resolve(request, note="Patched in 1.4.2")
    assert support_router.open_blocking_for(paying_client) is False


def test_the_post_resolution_prompt_asks_the_customer_not_us():
    assert support_router.POST_RESOLUTION_PROMPT == "Did this actually resolve it for you?"


def test_a_commercial_reply_to_support_is_blocked_by_governance():
    """
    THE RULE, ENFORCED IN CODE. Not by prompt wording — 'no matter how natural the segue
    seems' is exactly the judgement a helpful model gets wrong.
    """
    from apps.governance.services.claim_checker import check_support_reply

    decision = check_support_reply(
        "We have fixed the timeout. While we are here, would you like to discuss "
        "expanding to another workload?"
    )
    assert decision.status == "blocked"
    assert any("commercial_in_support" in v for v in decision.violations)


def test_a_pure_support_reply_passes():
    from apps.governance.services.claim_checker import check_support_reply

    decision = check_support_reply(
        "We have fixed the timeout in 1.4.2. Restart the runtime and it should clear."
    )
    assert decision.status == "auto_approved"
