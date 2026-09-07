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
TECH_PRISM = "prism"

_ROUTE_TECHS = {
    "undetermined": [],
    "astop": [TECH_PRISM],
    "alpha_compute": [TECH_AXIOM, TECH_CRE],
    "alpha_core": [TECH_FQNM, TECH_CRE],
    "both": [TECH_AXIOM, TECH_CRE, TECH_FQNM],
    "general": [],
}

_ROUTE_RATIONALE = {
    "undetermined": (
        "No product route has been assessed yet. Discovery signals can guide the next qualification question but do not establish product eligibility."
    ),
    "astop": (
        "ASTOP is the current controlled observation-product opportunity where observation relevance has been legitimately established; eligibility and evidence remain separately governed."
    ),
    "alpha_compute": (
        "Your problem looks representation-shaped, so ALPHA Compute — the independent software "
        "computational-infrastructure product — is the natural entry point for eligibility, transformation and proof."
    ),
    "alpha_core": (
        "Your problem looks hardware-integration-shaped, so an ALPHA Core hardware-layer evaluation may be relevant after a validated ALPHA software route is established."
    ),
    "both": (
        "Your problem spans software representation and possible deeper hardware integration. ALPHA Compute can stand alone in software; ALPHA Core is considered only where hardware implementation adds verified value."
    ),
    "general": (
        "No product route has been assessed yet; the historical general code is treated as neutral discovery rather than an ALPHA qualification."
    ),
}


def primary_technologies(product_route: str) -> list[str]:
    return _ROUTE_TECHS.get(product_route, _ROUTE_TECHS["undetermined"])


def route_rationale(product_route: str) -> str:
    return _ROUTE_RATIONALE.get(product_route, _ROUTE_RATIONALE["undetermined"])
