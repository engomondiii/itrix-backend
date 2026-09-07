"""
Next-step builder.

Builds ``recommendedNextStep`` — the single call-to-action tuned to the tier and route.
Higher tiers get a more direct, human next step; lower tiers get a lighter, educational
one. The wording matches the dashboard's tier "action" intent so on-site and CRM agree.
"""

from __future__ import annotations

_TIER_NEXT_STEP = {
    1: "Book a direct conversation with the itriX team to scope a strategic fit.",
    2: "Start a focused ALPHA evaluation to quantify the opportunity on a real workload.",
    3: "Get a personalized brief and a short follow-up to explore fit at your pace.",
    4: "Explore the approach with introductory material — no commitment needed.",
}

_ROUTE_HINT = {
    "alpha_compute": " We'd begin with an ALPHA Compute eligibility and software-path assessment.",
    "alpha_core": " We'd establish the ALPHA Compute software proof first, then evaluate whether an ALPHA Core hardware path adds value.",
    "both": " We'd begin with ALPHA Compute in software; ALPHA Core remains an optional hardware extension.",
    "general": "",
}


def build_next_step(*, tier: int, product_route: str) -> str:
    if product_route in {"undetermined", "general", ""}:
        return "Continue discovery without selecting a product route; qualification comes only after enough evidence is available."
    if product_route == "astop":
        return "If observation relevance is confirmed, scope a controlled ASTOP qualification/proof without implying later ALPHA progression."
    base = _TIER_NEXT_STEP.get(tier, _TIER_NEXT_STEP[3])
    hint = _ROUTE_HINT.get(product_route, "") if tier in (1, 2, 3) else ""
    return (base + hint).strip()
