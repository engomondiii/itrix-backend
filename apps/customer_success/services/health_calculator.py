"""
Customer health (Backend v6.0 §Phase 2, Architecture §18.7).

Health is what the customer-first NBA rule reads to decide whether a commercial action
may be ranked at all. So the calculation has one overriding property:

    IT NEVER RETURNS "STABLE" ON MISSING DATA.

An absent signal is UNKNOWN, and ``expansion_allowed`` refuses on unknown. The failure
mode this closes is a new customer with no recorded outcomes being classed as healthy by
default and immediately receiving an expansion CTA.

Four inputs, in precedence order — the first that fires decides:

    1. a blocking, unresolved support request      -> critical
    2. an outcome off plan                          -> at_risk
    3. a negative feedback pulse                    -> at_risk
    4. a degraded or down deployment                -> at_risk

Nothing here is a score. A class is auditable and explainable to an operator; a number
invites people to compare customers who are not comparable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.utils import timezone

logger = logging.getLogger("itrix")

HEALTH_UNKNOWN = ""
HEALTH_STABLE = "stable"
HEALTH_AT_RISK = "at_risk"
HEALTH_CRITICAL = "critical"

# How far back a feedback pulse still counts as current.
PULSE_WINDOW_DAYS = 90


@dataclass
class HealthAssessment:
    """The health class plus WHY — the reason is shown to the operator, never sold on."""

    health: str
    reasons: list[str] = field(default_factory=list)
    blocking_support: bool = False
    outcomes_off_plan: int = 0
    negative_pulse: bool = False
    degraded_deployments: int = 0

    @property
    def permits_expansion(self) -> bool:
        """Only a measured, stable customer may be offered an expansion."""
        return self.health == HEALTH_STABLE


def calculate(client) -> HealthAssessment:
    """Assess one customer's health from the signals actually recorded."""
    from apps.customer_success.models import (
        DeploymentHealth,
        FeedbackPulse,
        Outcome,
        OutcomeStatus,
        SupportRequest,
    )

    if client is None:
        return HealthAssessment(health=HEALTH_UNKNOWN, reasons=["no client"])

    reasons: list[str] = []

    blocking = SupportRequest.objects.filter(
        client=client, blocking=True, resolved_at__isnull=True
    ).exists()

    off_plan = Outcome.objects.filter(
        client=client, status__in=[OutcomeStatus.OFF_PLAN, OutcomeStatus.AT_RISK]
    ).count()

    cutoff = timezone.now() - timezone.timedelta(days=PULSE_WINDOW_DAYS)
    negative_pulse = FeedbackPulse.objects.filter(
        client=client, created_at__gte=cutoff, score__lte=2
    ).exists()

    degraded = DeploymentHealth.objects.filter(
        client=client, status__in=[DeploymentHealth.Status.DEGRADED, DeploymentHealth.Status.DOWN]
    ).count()

    # Precedence order — the first that fires decides the class.
    if blocking:
        reasons.append("a blocking support request is open")
        health = HEALTH_CRITICAL
    elif off_plan:
        reasons.append(f"{off_plan} outcome(s) are off plan or at risk")
        health = HEALTH_AT_RISK
    elif negative_pulse:
        reasons.append("recent feedback was negative")
        health = HEALTH_AT_RISK
    elif degraded:
        reasons.append(f"{degraded} deployment(s) are degraded or down")
        health = HEALTH_AT_RISK
    else:
        health = _stable_or_unknown(client, reasons)

    return HealthAssessment(
        health=health,
        reasons=reasons,
        blocking_support=blocking,
        outcomes_off_plan=off_plan,
        negative_pulse=negative_pulse,
        degraded_deployments=degraded,
    )


def _stable_or_unknown(client, reasons: list[str]) -> str:
    """
    No bad signal is not the same as a good signal.

    A customer with NOTHING recorded — no outcomes, no deployments — is UNKNOWN. Calling
    them stable would let a brand-new customer with an empty workspace receive an
    expansion CTA on their first visit.
    """
    from apps.customer_success.models import DeploymentHealth, Outcome

    has_outcomes = Outcome.objects.filter(client=client).exists()
    has_deployments = DeploymentHealth.objects.filter(client=client).exists()

    if not (has_outcomes or has_deployments):
        reasons.append("no outcomes or deployments recorded yet")
        return HEALTH_UNKNOWN

    reasons.append("no blocking issues, off-plan outcomes or negative feedback")
    return HEALTH_STABLE


def recompute(client) -> str:
    """Assess and PERSIST the health class onto the Client. Returns the class."""
    assessment = calculate(client)
    if getattr(client, "customer_health", None) != assessment.health:
        client.customer_health = assessment.health
        try:
            client.save(update_fields=["customer_health", "updated_at"])
        except Exception:  # noqa: BLE001
            logger.exception("could not persist health for client %s", client.id)
    return assessment.health


def recompute_all() -> dict:
    """Nightly sweep. Returns a distribution for the cockpit."""
    from apps.clients.models import Client

    distribution: dict[str, int] = {}
    for client in Client.objects.filter(is_active=True).iterator():
        health = recompute(client)
        distribution[health or "unknown"] = distribution.get(health or "unknown", 0) + 1
    logger.info("customer_health.recompute_all %s", distribution)
    return distribution
