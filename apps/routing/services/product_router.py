"""
Product router.

Maps qualification answers to an ALPHA product route. Representation-shaped problems
(state estimation, dense/complex linear algebra) lean **ALPHA Compute**; execution /
runtime-shaped problems (conservation-law dynamics, custom hardware, data-movement or
hardware-utilisation pressure) lean **ALPHA Core**; broad or mixed cases map to
**both**; unclear cases map to **general**.

This is the authoritative server-side version of
``itrix-web/src/lib/routing/productRouter.ts`` and returns identical results, so the
client's provisional route and the backend's agree.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import (
    EXECUTION_ENVIRONMENTS,
    EXECUTION_PRESSURES,
    PRODUCT_ALPHA_COMPUTE,
    PRODUCT_ALPHA_CORE,
    PRODUCT_BOTH,
    PRODUCT_GENERAL,
    REPRESENTATION_STRUCTURES,
    multi,
    single,
)


class ProductRouter:
    """Stateless product-routing logic."""

    @staticmethod
    def route(answers: dict) -> str:
        structure = single(answers.get("Q3"))
        env = single(answers.get("Q1"))
        pressures = multi(answers.get("Q2"))

        representation_signal = structure in REPRESENTATION_STRUCTURES
        execution_signal = (
            structure == "conservation"
            or env in EXECUTION_ENVIRONMENTS
            or any(p in EXECUTION_PRESSURES for p in pressures)
        )

        if structure == "mixed":
            return PRODUCT_BOTH
        if representation_signal and execution_signal:
            return PRODUCT_BOTH
        if representation_signal:
            return PRODUCT_ALPHA_COMPUTE
        if execution_signal:
            return PRODUCT_ALPHA_CORE
        if not structure or structure == "unsure":
            return PRODUCT_GENERAL
        return PRODUCT_ALPHA_COMPUTE


def route_product(answers: dict) -> str:
    """Module-level convenience wrapper."""
    return ProductRouter.route(answers)
