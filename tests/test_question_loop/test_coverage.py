"""
The coverage tracker — DETERMINISTIC, LLM-FREE (Backend v6.0 §5.1, §5.2).

Layer 1 stays LLM-free precisely so the loop can be TRUSTED TO TERMINATE. If a model
decided coverage, a model would decide when qualification ends — and a model having a
pleasant conversation has every incentive to keep having it.
"""

from __future__ import annotations

import pytest

from apps.agents.services import coverage as coverage_svc
from apps.journey.constants import LISTENING_DIMENSIONS
from tests.test_question_loop.conftest import add_turn

pytestmark = pytest.mark.django_db


def test_all_ten_dimensions_are_tracked(thread):
    coverage = coverage_svc.build_for_thread(thread)
    assert set(coverage.dimensions) == set(LISTENING_DIMENSIONS)
    assert len(LISTENING_DIMENSIONS) == 10


def test_an_empty_thread_covers_nothing(thread):
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.covered() == []


def test_a_strong_signal_covers_a_dimension(thread):
    add_turn(thread, "Our inference workload is the problem")
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.status("workload") == coverage_svc.COVERED


def test_platform_and_pressure_are_recognised(thread):
    add_turn(thread, "We run PyTorch on a GPU cluster and the cost is rising fast")
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.status("platform_environment") == coverage_svc.COVERED
    assert coverage.status("pressure_area") == coverage_svc.COVERED


def test_coverage_only_moves_forward(thread):
    """
    A later vague turn must not downgrade a dimension the visitor already answered
    clearly — otherwise the loop could re-ask something it was told.
    """
    add_turn(thread, "We run PyTorch on a GPU cluster")
    add_turn(thread, "Anyway, about the platform, not sure")
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.status("platform_environment") == coverage_svc.COVERED


def test_coverage_is_deterministic():
    """Same input, same answer — every time, with no model in the path."""
    text = "Our CFD solver is slow on the HPC cluster and memory movement dominates"
    first = coverage_svc.analyse_text(text)
    second = coverage_svc.analyse_text(text)
    assert first == second


def test_the_tracker_makes_no_model_call():
    """
    Layer 1 is LLM-FREE. Asserted on the module's IMPORTS rather than its text — the
    docstring legitimately discusses why embeddings are not used, and a naive substring
    scan would flag the explanation of the rule as a breach of it.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(coverage_svc))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for module in imported:
        lowered = module.lower()
        for forbidden in ("claude", "openai", "anthropic", "ai_engine", "embed"):
            assert forbidden not in lowered, (
                f"coverage imports {module!r} — Layer 1 must stay LLM-free"
            )


def test_attachment_text_counts_toward_coverage(thread):
    """
    A visitor who uploads their architecture doc has told us about their platform just
    as surely as if they had typed it.
    """
    from apps.attachments.services import intake

    intake.process(
        intake.stage(
            thread=thread, filename="stack.txt",
            data=b"We run PyTorch training on a CUDA GPU cluster",
            declared_mime="text/plain",
        )
    )
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.status("platform_environment") == coverage_svc.COVERED


def test_required_dimensions_gate_completeness(thread):
    add_turn(thread, "Our training workload is the issue")
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.is_complete_for(2) is False

    add_turn(thread, "It runs on a GPU cluster and the cost is unsustainable")
    coverage = coverage_svc.build_for_thread(thread)
    assert coverage.is_complete_for(2) is True


def test_state_one_requires_nothing(thread):
    assert coverage_svc.build_for_thread(thread).is_complete_for(1) is True
