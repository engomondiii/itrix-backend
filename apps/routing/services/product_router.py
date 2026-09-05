"""Discovery-stage product relevance without premature commercial routing.

Qualification answers can reveal *signals* about a problem.  They cannot, by themselves,
open an ASTOP/ALPHA opportunity or assign a governed product route.  Current GTM requires
ASTOP controlled proof first where legitimately established, a separate ALPHA Compute
qualification for a deeper workload, and ALPHA Core only after validated software-layer
evidence supports hardware.

``route_product`` therefore returns the neutral route for this legacy Q1–Q9 surface.
``product_hypotheses`` preserves the useful bounded signals for diagnostics/analytics
without turning them into qualification.
"""
from __future__ import annotations

from apps.routing.services.routing_rules import (
    EXECUTION_ENVIRONMENTS,
    EXECUTION_PRESSURES,
    PRODUCT_ALPHA_COMPUTE,
    PRODUCT_ALPHA_CORE,
    PRODUCT_ASTOP,
    PRODUCT_UNDETERMINED,
    REPRESENTATION_STRUCTURES,
    multi,
    single,
)


class ProductRouter:
    """Stateless discovery-signal classifier; never a commercial gate."""

    @staticmethod
    def hypotheses(answers: dict) -> list[str]:
        structure = single(answers.get("Q3"))
        env = single(answers.get("Q1"))
        pressures = multi(answers.get("Q2"))

        out: list[str] = []
        # Observation/state language can be worth exploring in ASTOP/PRISM, but this is
        # only relevance, not an ASTOP opportunity.
        if structure == "state_observation":
            out.append(PRODUCT_ASTOP)

        representation_signal = structure in REPRESENTATION_STRUCTURES
        execution_signal = (
            structure == "conservation"
            or env in EXECUTION_ENVIRONMENTS
            or any(p in EXECUTION_PRESSURES for p in pressures)
        )
        if representation_signal:
            out.append(PRODUCT_ALPHA_COMPUTE)
        if execution_signal:
            out.append(PRODUCT_ALPHA_CORE)
        return list(dict.fromkeys(out))

    @staticmethod
    def route(answers: dict) -> str:
        # Intentionally evaluate the bounded hypotheses so callers/tests can exercise the
        # same signal logic, but never translate a keyword/answer into a binding route.
        ProductRouter.hypotheses(answers)
        return PRODUCT_UNDETERMINED


def product_hypotheses(answers: dict) -> list[str]:
    return ProductRouter.hypotheses(answers)


def route_product(answers: dict) -> str:
    """Return the governed discovery-stage route: not yet assessed."""
    return ProductRouter.route(answers)
