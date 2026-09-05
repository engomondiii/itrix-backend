"""Discovery routing must preserve hypotheses without fabricating qualification."""
from __future__ import annotations

from apps.routing.services.product_router import product_hypotheses, route_product
from tests.factories.scoring_factory import EXECUTION_ANSWERS, REPRESENTATION_ANSWERS


def test_representation_is_only_a_hypothesis_until_governed_gate():
    assert "alpha_compute" in product_hypotheses(REPRESENTATION_ANSWERS)
    assert route_product(REPRESENTATION_ANSWERS) == "undetermined"


def test_execution_signal_cannot_open_alpha_core_directly():
    assert "alpha_core" in product_hypotheses(EXECUTION_ANSWERS)
    assert route_product(EXECUTION_ANSWERS) == "undetermined"


def test_state_observation_can_note_astop_relevance_without_binding_route():
    answers = {"Q1": "python_scipy", "Q2": ["cost"], "Q3": "state_observation"}
    hints = product_hypotheses(answers)
    assert "astop" in hints
    assert route_product(answers) == "undetermined"


def test_mixed_structure_does_not_create_multi_product_route():
    answers = {"Q1": "hardware", "Q2": ["memory_data_movement"], "Q3": "mixed"}
    assert route_product(answers) == "undetermined"


def test_unsure_remains_unassessed():
    answers = {"Q1": "", "Q2": [], "Q3": "unsure"}
    assert product_hypotheses(answers) == []
    assert route_product(answers) == "undetermined"


def test_q2_can_be_scalar_or_list_without_changing_gate_semantics():
    scalar = {"Q1": "hardware", "Q2": "memory_data_movement", "Q3": "conservation"}
    assert "alpha_core" in product_hypotheses(scalar)
    assert route_product(scalar) == "undetermined"
