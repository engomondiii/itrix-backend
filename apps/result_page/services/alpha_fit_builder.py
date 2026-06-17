"""
ALPHA-fit summary builder.

Builds ``alphaFitSummary`` — a couple of sentences on how ALPHA fits the visitor's
situation, combining the route rationale with their tier (how engaged a next step is
appropriate). Stays qualitative and within claims discipline.
"""

from __future__ import annotations

from apps.result_page.services.product_route_explainer import route_rationale

_TIER_FIT = {
    1: "Your profile is a strong strategic fit, so a direct conversation is the most useful next step.",
    2: "Your profile is a good fit; a focused evaluation would tell us quickly how much ALPHA can help.",
    3: "There's a plausible fit worth exploring with a short, no-pressure review.",
    4: "It's early, and some background on the approach is probably the most useful thing right now.",
}


def build_alpha_fit_summary(*, product_route: str, tier: int) -> str:
    return f"{route_rationale(product_route)} {_TIER_FIT.get(tier, _TIER_FIT[3])}".strip()
