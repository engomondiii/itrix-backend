"""Keep denormalized cross-product state aligned when governed records change."""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.evaluations.models import Evaluation, EvaluationPackage
from apps.leads.models import ASTOPEngagement, Lead

# Fee deliberation/finalization is intentionally orthogonal to product progression.
_FEE_ONLY_FIELDS = {
    "ai_waiver_decision",
    "waiver_type",
    "waiver_percentage_or_amount",
    "waiver_reason",
    "waiver_expiry",
    "iwl_override_status",
    "iwl_override_applied",
    "iwl_override_reason",
    "standard_assessment_fee",
    "final_assessment_fee",
    "final_authority",
    "fee_finalized_at",
    "customer_fee_status",
    "updated_at",
}


def _sync(lead) -> None:
    try:
        from apps.leads.services.progression_state import sync_progression_state

        sync_progression_state(lead, audit=False)
    except Exception:
        # A denormalized synchronization failure must never make the authoritative
        # ASTOP/Evaluation write disappear. Read consumers still derive state directly.
        return


@receiver(post_save, sender=ASTOPEngagement)
def _astop_changed(sender, instance, **kwargs):
    _sync(instance.lead)


@receiver(post_save, sender=Evaluation)
def _evaluation_changed(sender, instance, update_fields=None, **kwargs):
    if update_fields and set(update_fields).issubset(_FEE_ONLY_FIELDS):
        return

    # Do not reinterpret unrelated legacy/default-package evaluation rows as a governed
    # product promotion unless ASTOP progression already exists. A Core opportunity is
    # always governed by construction, so it is eligible regardless of this filter.
    if instance.pkg != EvaluationPackage.CORE:
        if not ASTOPEngagement.objects.filter(lead_id=instance.lead_id).exists():
            return
    _sync(instance.lead)


@receiver(post_save, sender=Lead)
def _lead_denormalized_progress_changed(sender, instance, update_fields=None, **kwargs):
    """Correct writer-local stale next-action assignments after their authoritative save."""
    if update_fields is not None and not {
        "current_marketing_stage",
        "commercial_progress",
    }.intersection(set(update_fields)):
        return

    from apps.leads.services.progression_state import is_syncing

    if is_syncing(instance.pk):
        return
    # Only engage once this lead has entered governed product progression. Acquisition,
    # trusted-introduction and fee-only writes do not touch these fields and never arrive.
    if not ASTOPEngagement.objects.filter(lead_id=instance.pk).exists() and not Evaluation.objects.filter(
        lead_id=instance.pk,
        pkg__in=[EvaluationPackage.COMPUTE, EvaluationPackage.CORE],
    ).exists():
        return
    _sync(instance)
