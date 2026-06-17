"""
Product-route explainer.

Maps the routed product code to (a) the display route the web expects and (b) the set of
primary technologies (AXIOM / CRE / FQNM) to highlight, plus a short rationale used by the
ALPHA-fit summary. The TechnologyId values match the web ``product.types.ts``.
"""

from __future__ import annotations

# Canonical technology ids (web TechnologyId).
TECH_AXIOM = "axiom"
TECH_CRE = "cre"
TECH_FQNM = "fqnm"

_ROUTE_TECHS = {
    "alpha_compute": [TECH_AXIOM, TECH_CRE],
    "alpha_core": [TECH_FQNM, TECH_CRE],
    "both": [TECH_AXIOM, TECH_CRE, TECH_FQNM],
    "general": [TECH_AXIOM],
}

_ROUTE_RATIONALE = {
    "alpha_compute": (
        "Your problem looks representation-shaped, so ALPHA Compute — representation-level "
        "diagnosis — is the natural entry point."
    ),
    "alpha_core": (
        "Your problem looks execution-shaped, so ALPHA Core — the runtime/execution layer — "
        "is the natural entry point."
    ),
    "both": (
        "Your problem spans representation and execution, so both ALPHA Compute and ALPHA Core "
        "are relevant; we'd typically start with a Compute diagnosis."
    ),
    "general": (
        "A general ALPHA review is the right first step to locate where the bottleneck really sits."
    ),
}


def primary_technologies(product_route: str) -> list[str]:
    return _ROUTE_TECHS.get(product_route, _ROUTE_TECHS["general"])


def route_rationale(product_route: str) -> str:
    return _ROUTE_RATIONALE.get(product_route, _ROUTE_RATIONALE["general"])
