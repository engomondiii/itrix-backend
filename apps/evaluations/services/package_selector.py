"""
Package selector.

Chooses the right evaluation package from a lead's product route: ALPHA Compute →
Compute Bottleneck Assessment, ALPHA Core → Core Runtime Fit Assessment, both → Combined.
"""

from __future__ import annotations

from apps.evaluations.models import EvaluationPackage

_ROUTE_TO_PACKAGE = {
    "alpha_compute": EvaluationPackage.COMPUTE,
    "alpha_core": EvaluationPackage.CORE,
    "both": EvaluationPackage.COMBINED,
    "general": EvaluationPackage.COMPUTE,
}


def select_package(product_route: str) -> str:
    return _ROUTE_TO_PACKAGE.get(product_route, EvaluationPackage.COMPUTE).value
