"""
A question NEVER reveals an inference (Architecture §4, §19.5).

    PERSONALIZATION WITHOUT PROFILING
    Personalization means the framing, the emphasis and the chosen pathway are tailored.
    It NEVER means telling the visitor what we think we know about them. The most
    tailored pitch and the safest pitch must be THE SAME PITCH.

    This applies with equal force to a generated question: a question may not reveal an
    inference.
"""

from __future__ import annotations

import pytest

from apps.agents.services import question_generator as qg

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("text", [
    "Since you're at a hyperscaler, how many regions?",
    "Based on your company, would ALPHA Core suit you?",
    "We identified you as an infrastructure team — is that right?",
    "Your department is platform engineering, correct?",
])
def test_identity_revealing_questions_are_rejected(text):
    assert qg.check_candidate(text) != ""


def test_the_generator_never_puts_a_persona_in_the_payload(thread):
    from apps.agents.services import coverage as coverage_svc

    coverage = coverage_svc.CoverageMap(
        dimensions={d: coverage_svc.UNKNOWN for d in coverage_svc.LISTENING_DIMENSIONS}
    )
    payload = qg.emit(thread, qg.generate(thread=thread, coverage=coverage, journey_state=2))
    rendered = str(payload)
    for leak in ("persona", "tier", "score", "P-0", "PR-"):
        assert leak not in rendered


def test_the_model_prompt_forbids_revealing_an_inference():
    """
    The system prompt is the model's only instruction; the rules that matter must be in
    it explicitly rather than implied.
    """
    import inspect

    source = inspect.getsource(qg._generate_wording)
    assert "never state or imply anything about the visitor" in source.lower()
    assert "never request confidential" in source.lower()
    assert "may never assert" in source.lower()


def test_generation_is_low_temperature_and_bounded():
    """The model rewords an APPROVED question; it does not compose a new one."""
    import inspect

    source = inspect.getsource(qg._generate_wording)
    assert "Approved question to rephrase" in source
    assert "must remain the SAME question" in source


def test_a_rejected_candidate_falls_back_rather_than_emitting(thread, monkeypatch):
    """A guard failure must not skip the question — it uses the approved bank version."""
    from apps.agents.services import coverage as coverage_svc

    monkeypatch.setattr(
        qg, "_generate_wording",
        lambda *a, **k: "Since you're a chip company, what is your node?",
    )
    coverage = coverage_svc.CoverageMap(
        dimensions={d: coverage_svc.UNKNOWN for d in coverage_svc.LISTENING_DIMENSIONS}
    )
    question = qg.generate(thread=thread, coverage=coverage, journey_state=2)
    assert question.generated is False
    assert question.rejected_reason == "inferred_identity"
    assert question.primary in [e["primary"] for e in qg.QUESTION_BANK.values()]
