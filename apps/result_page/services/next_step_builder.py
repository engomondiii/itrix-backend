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
    "alpha_compute": " We'd begin with an ALPHA Compute representation diagnosis.",
    "alpha_core": " We'd begin with an ALPHA Core runtime-fit review.",
    "both": " We'd typically begin with a Compute diagnosis, then a Core review.",
    "general": "",
}


def build_next_step(*, tier: int, product_route: str) -> str:
    base = _TIER_NEXT_STEP.get(tier, _TIER_NEXT_STEP[3])
    hint = _ROUTE_HINT.get(product_route, "") if tier in (1, 2, 3) else ""
    return (base + hint).strip()
