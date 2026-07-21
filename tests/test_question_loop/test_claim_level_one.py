"""
A generated question MAY ASK, NEVER ASSERT (Backend v6.0 §5.4).

Every generated question is:
  * bound to Claim-Card level 1
  * checked against the prohibited-language list before emission
  * forbidden from naming or implying an inferred company, department, persona or score
  * forbidden from requesting confidential information before an NDA
"""

from __future__ import annotations

import pytest

from apps.agents.services import question_generator as qg

pytestmark = pytest.mark.django_db


def test_the_claim_level_is_one():
    assert qg.CLAIM_LEVEL == 1


def test_a_plain_question_passes():
    assert qg.check_candidate("What does the workload run on today?") == ""


def test_a_statement_is_rejected():
    """It must actually be a question. A statement dressed as guidance is an assertion."""
    assert qg.check_candidate("Your workload is memory-bound.") == "not_a_question"


@pytest.mark.parametrize("text,reason", [
    ("Since you're a semiconductor company, what is your process node?", "inferred_identity"),
    ("We can see you are running at scale — how many nodes?", "inferred_identity"),
    ("As a large enterprise team, what is your budget?", "inferred_identity"),
])
def test_inferred_identity_is_rejected(text, reason):
    """
    PERSONALIZATION WITHOUT PROFILING (§4). A question may never reveal an inference.
    """
    assert qg.check_candidate(text) == reason


def test_asking_for_confidential_material_is_rejected():
    assert qg.check_candidate(
        "Could you share your proprietary code so we can look?"
    ) == "pre_nda_confidential"


def test_a_figure_in_a_question_is_rejected():
    """A question carrying a figure is smuggling a claim."""
    assert qg.check_candidate("Would a 40% faster solver help you?") == "figure"


def test_a_guarantee_in_a_question_is_rejected():
    assert qg.check_candidate("We guarantee improvement — when could you start?") == "assertion"


def test_an_internal_signal_is_rejected():
    assert qg.check_candidate("You look like a tier 1 account — is that right?") == "internal_signal"


def test_every_bank_question_passes_its_own_guard():
    """
    The fallback must be safe, because it is what gets used whenever generation is
    unavailable — which is most of the time in a degraded deployment.
    """
    for dimension, entry in qg.QUESTION_BANK.items():
        reason = qg.check_candidate(entry["primary"])
        assert reason == "", f"bank question for {dimension} fails its own guard: {reason}"


def test_the_bank_covers_every_dimension():
    from apps.journey.constants import LISTENING_DIMENSIONS

    assert set(qg.QUESTION_BANK) == set(LISTENING_DIMENSIONS)


def test_chips_never_exceed_three():
    for entry in qg.QUESTION_BANK.values():
        assert len(entry.get("chips", [])) <= qg.MAX_CHIPS


def test_governance_refuses_a_question_above_level_one():
    from apps.governance.services.claim_checker import check_generated_question

    decision = check_generated_question("Would a guaranteed 50% saving interest you?")
    assert decision.status == "blocked"
