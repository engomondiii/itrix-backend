"""Product-router tests — verify routing matches the frontend logic."""

from __future__ import annotations

from apps.routing.services.product_router import route_product
from tests.factories.scoring_factory import EXECUTION_ANSWERS, REPRESENTATION_ANSWERS


def test_representation_routes_to_alpha_compute():
    assert route_product(REPRESENTATION_ANSWERS) == "alpha_compute"


def test_execution_routes_to_alpha_core():
    assert route_product(EXECUTION_ANSWERS) == "alpha_core"


def test_mixed_structure_routes_to_both():
    answers = {"Q1": "python_scipy", "Q2": ["cost"], "Q3": "mixed"}
    assert route_product(answers) == "both"


def test_representation_plus_execution_signal_routes_to_both():
    answers = {"Q1": "hardware", "Q2": ["memory_data_movement"], "Q3": "linear_algebra"}
    assert route_product(answers) == "both"


def test_unsure_routes_to_general():
    answers = {"Q1": "", "Q2": [], "Q3": "unsure"}
    assert route_product(answers) == "general"


def test_q2_can_be_scalar_or_list():
    # The router must tolerate a scalar Q2 (single pressure) as well as a list.
    scalar = {"Q1": "hardware", "Q2": "memory_data_movement", "Q3": "conservation"}
    assert route_product(scalar) == "alpha_core"
