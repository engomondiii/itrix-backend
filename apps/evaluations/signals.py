"""Evaluation lifecycle hooks for deterministic fee-policy orchestration."""
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.evaluations.models import Evaluation, EvaluationPackage, TechnicalRoute

logger = logging.getLogger("itrix")


@receiver(post_save, sender=Evaluation, dispatch_uid="evaluations.alpha_fee_policy_orchestration")
def orchestrate_new_alpha_assessment(sender, instance: Evaluation, created: bool, **kwargs) -> None:
    """Wire every newly-created governed ALPHA Compute assessment to policy once.

    Legacy/general Evaluation rows have no separate_workload/technical route and are left
    alone. The hook runs only on create, so the decision service's own save cannot recurse.
    """
    if not created or instance.pkg != EvaluationPackage.COMPUTE:
        return
    if not str(instance.separate_workload or "").strip():
        return
    if instance.technical_route == TechnicalRoute.NONE:
        return
    try:
        from apps.evaluations.services.fee_policy_orchestrator import orchestrate_assessment_fee_policy

        orchestrate_assessment_fee_policy(instance)
    except Exception:
        # Fee orchestration must fail safe, not fail the substantive assessment creation.
        # The Evaluation default is paid; no exception can turn a missing policy result
        # into a waiver. Operators can see the failure in logs and retry the deterministic
        # orchestration without duplicating a recorded outcome.
        logger.exception("alpha fee-policy orchestration failed for evaluation %s", instance.pk)
