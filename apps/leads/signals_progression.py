"""Keep denormalized cross-product state aligned when governed records change."""
from __future__ import annotations

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.core.exceptions import ResourceConflict
from apps.evaluations.models import Evaluation, EvaluationPackage
from apps.leads.models import ASTOPEngagement, ASTOPStage, Lead, TrustStatus

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
_ENTITLEMENT_FIELDS = {
    "entitlement_status",
    "entitlement_expires_at",
    "revocation_status",
}


def _sync(lead) -> None:
    try:
        from apps.leads.services.progression_state import sync_progression_state

        sync_progression_state(lead, audit=False)
    except Exception:
        # A denormalized synchronization failure must never make the authoritative
        # ASTOP/Evaluation write disappear. Read consumers still derive state directly.
        return


@receiver(pre_save, sender=Lead)
def _protect_governed_trust_resolution(sender, instance, update_fields=None, **kwargs):
    """Prevent legacy/direct writers from bypassing an established REVIEW/REJECT state."""
    if instance._state.adding:
        return
    if update_fields is not None and not {
        "trust_status",
        "trust_screening",
    }.intersection(set(update_fields)):
        return

    previous = Lead.objects.filter(pk=instance.pk).values("trust_status", "trust_screening").first()
    if previous is None or previous["trust_status"] not in {TrustStatus.REVIEW, TrustStatus.REJECT}:
        return

    changed = (
        previous["trust_status"] != instance.trust_status
        or previous["trust_screening"] != instance.trust_screening
    )
    if not changed:
        return

    from apps.leads.services.human_review import is_governed_trust_review_write

    if is_governed_trust_review_write(instance.pk):
        return
    raise ResourceConflict(
        "Existing REVIEW/REJECT trust state must be handled through the governed trust-review workflow."
    )


@receiver(pre_save, sender=ASTOPEngagement)
def _protect_lo_execution_and_entitlement_writers(sender, instance, update_fields=None, **kwargs):
    """Protect executed-LO truth and keep entitlement changes on their governed writer."""
    if instance._state.adding:
        return

    previous = ASTOPEngagement.objects.filter(pk=instance.pk).values(
        "lo_executed_at", *_ENTITLEMENT_FIELDS
    ).first()
    if previous is None:
        return

    if update_fields is None or "lo_executed_at" in set(update_fields):
        before_execution = previous["lo_executed_at"]
        after_execution = instance.lo_executed_at
        if before_execution != after_execution:
            if before_execution is not None:
                raise ResourceConflict("Executed ASTOP License-Out timestamp is immutable.")
            if after_execution is not None:
                if instance.stage not in {ASTOPStage.LO_DEPLOYMENT, ASTOPStage.VERIFY_EXPAND}:
                    raise ResourceConflict(
                        "ASTOP License-Out may only be executed from the governed License-Out stage."
                    )
                from apps.leads.services.lo_terms import governed_terms_gate

                reasons = governed_terms_gate(instance)
                if reasons:
                    raise ResourceConflict(
                        "ASTOP License-Out execution requires final governed terms and scope."
                    )

    if update_fields is not None and not _ENTITLEMENT_FIELDS.intersection(set(update_fields)):
        return
    changed = any(previous[field] != getattr(instance, field) for field in _ENTITLEMENT_FIELDS)
    if not changed:
        return

    from apps.leads.services.entitlement_lifecycle import is_governed_entitlement_write

    if is_governed_entitlement_write(instance.pk):
        return
    raise ResourceConflict(
        "ASTOP entitlement state must be changed through the governed astop-entitlement lifecycle."
    )


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
