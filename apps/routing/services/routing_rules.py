"""
Routing rules — shared constants and answer-access helpers.

Centralises the option values and signal sets used by the product/license/room
routers, so all three stay consistent with the frontend
(``itrix-web/src/lib/routing/*`` and ``src/config/review.config.ts``).
"""

from __future__ import annotations

# ── Canonical product-route codes (match the web result/qualify contract) ────
PRODUCT_ALPHA_COMPUTE = "alpha_compute"
PRODUCT_ALPHA_CORE = "alpha_core"
PRODUCT_BOTH = "both"
PRODUCT_GENERAL = "general"

# ── Canonical license-pathway codes ──────────────────────────────────────────
LICENSE_NON_EXCLUSIVE = "non_exclusive"
LICENSE_EXCLUSIVE = "exclusive"
LICENSE_STRATEGIC = "strategic"

# ── Q3 (workload structure) values ───────────────────────────────────────────
REPRESENTATION_STRUCTURES = {"state_observation", "linear_algebra"}
EXECUTION_STRUCTURES = {"conservation"}

# ── Q1 (environment) values that imply an execution/runtime emphasis ─────────
EXECUTION_ENVIRONMENTS = {"hardware", "native"}

# ── Q2 (pressure) values that imply an execution/runtime emphasis ────────────
EXECUTION_PRESSURES = {"hardware_utilization", "memory_data_movement"}

# ── Q6 (organization) values that lean strategic for licensing ───────────────
STRATEGIC_ORG_TYPES = {"hardware_chip", "cloud_infra"}


def single(value) -> str | None:
    """Coerce a possibly-list answer to a single value (first element) or None."""
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


def multi(value) -> list[str]:
    """Coerce a possibly-scalar answer to a list."""
    if isinstance(value, list):
        return value
    return [value] if value else []
