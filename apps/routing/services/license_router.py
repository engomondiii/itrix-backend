"""
License router.

Maps the licensing-interest answer (Q9) plus the organization type (Q6) to a
commercial pathway, or ``None`` when the visitor only wants product use / is unsure.

Mirrors ``itrix-web/src/lib/routing/licenseRouter.ts``.
"""

from __future__ import annotations

from apps.routing.services.routing_rules import (
    LICENSE_EXCLUSIVE,
    LICENSE_NON_EXCLUSIVE,
    LICENSE_STRATEGIC,
    STRATEGIC_ORG_TYPES,
    single,
)


class LicenseRouter:
    """Stateless license-routing logic."""

    @staticmethod
    def route(answers: dict) -> str | None:
        interest = single(answers.get("Q9"))
        org = single(answers.get("Q6"))

        if interest == "exclusive":
            # Hardware / cloud orgs with exclusivity interest lean strategic.
            return LICENSE_STRATEGIC if org in STRATEGIC_ORG_TYPES else LICENSE_EXCLUSIVE
        if interest == "non_exclusive":
            return LICENSE_NON_EXCLUSIVE
        return None  # product_only / unsure / unanswered


def route_license(answers: dict) -> str | None:
    """Module-level convenience wrapper."""
    return LicenseRouter.route(answers)
