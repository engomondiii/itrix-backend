"""
A support question is NEVER answered with a commercial claim
(Architecture §19.5, Playbook §12D, Backend v6.0 §11.2).

    A support reply helps with the problem and stops. It does not mention another
    workload, an expansion, a renewal, or a next agreement — NO MATTER HOW NATURAL THE
    SEGUE SEEMS.

    Enforced IN THE CLAIM CHECKER, not by prompt wording.

That last clause is the design decision under test. "No matter how natural the segue
seems" is precisely the judgement a helpful model gets wrong, so it is not left to one.
"""

from __future__ import annotations

import pytest

from apps.ai_engine.services import prohibited_language_checker as plc
from apps.governance.services.claim_checker import check_support_reply

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("reply", [
    "We fixed the timeout. While we are here, would you like to discuss expanding?",
    "That is resolved. Have you considered adding another workload?",
    "Patched in 1.4.2 — a good time to talk about your renewal.",
    "Fixed. This would also benefit your other team.",
    "Resolved. Would you like to look at extending your licence?",
    "Done. Now might be a good moment to discuss the next agreement.",
])
def test_a_commercial_segue_is_blocked(reply):
    decision = check_support_reply(reply)
    assert decision.status == "blocked"
    assert any("commercial_in_support" in v for v in decision.violations)


@pytest.mark.parametrize("reply", [
    "We fixed the timeout in 1.4.2. Restart the runtime and it should clear.",
    "That is a known limitation on the 1.3 line. The fix ships next week.",
    "We reproduced it. Your technical owner will follow up with a patch today.",
    "Not resolved yet — we are still investigating and will update you by Friday.",
])
def test_a_pure_support_reply_passes(reply):
    assert check_support_reply(reply).status == "auto_approved"


def test_the_pattern_set_is_single_sourced():
    """
    §11.1: the prohibited-pattern set has EXACTLY ONE DEFINITION, so a pattern cannot be
    enforced at settle but missed mid-stream. The claim checker must not restate it.
    """
    import inspect

    from apps.governance.services import claim_checker

    source = inspect.getsource(claim_checker.check_support_reply)
    assert "prohibited_language_checker" in source
    # The patterns themselves must NOT be redefined in the governance module.
    assert not hasattr(claim_checker, "_COMMERCIAL_IN_SUPPORT")


def test_the_checker_exposes_what_matched():
    """The cockpit needs to see WHICH phrase tripped it, not just that something did."""
    matched = plc.find_commercial_in_support(
        "Fixed. Would you like to discuss expanding to another workload?"
    )
    assert matched


def test_an_empty_reply_is_not_flagged():
    assert plc.has_commercial_in_support("") is False


def test_a_blocking_support_issue_suppresses_the_commercial_action(paying_client=None):
    """
    The other half of the rule: not just the WORDS, but the ACTION.

    Even a perfectly-worded support reply must not be accompanied by a commercial next
    step while the issue is open.
    """
    from apps.governance.services import nba_precedence as nba

    decision = nba.rank(
        [nba.ActionCandidate(key="expand", label="Expand", kind=nba.KIND_COMMERCIAL,
                             commercial=True, weight=100)],
        signals={
            "blocking_support": True, "outcome_off_plan": False,
            "adoption_below_plan": False, "negative_trust": False,
            "health": "stable", "expansion_allowed": True,
        },
    )
    assert decision.primary.commercial is False
    assert decision.suppression_reason == nba.SUPPRESSED_BLOCKING_SUPPORT
