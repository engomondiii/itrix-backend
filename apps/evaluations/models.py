"""
Evaluation models.

``Evaluation`` tracks a paid evaluation through proposed → in_progress → delivered → won/lost,
with a list of KPI rows. Matches the dashboard's ``Evaluation`` type
(``{id, leadId, leadName, company, pkg, status, kpis[], createdAt, updatedAt}``) and
``EvaluationKPI`` (``{id, category, metric, target?, result?}``). KPIs are stored as JSON.
The package strings match the dashboard's ``EVALUATION_PACKAGES``.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class EvaluationStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    IN_PROGRESS = "in_progress", "In progress"
    DELIVERED = "delivered", "Delivered"
    WON = "won", "Won"
    LOST = "lost", "Lost"


class TechnicalRoute(models.TextChoices):
    NONE = "none", "None / not yet selected"
    AXIOM = "axiom", "AXIOM"
    AXIOM_TENSOR = "axiom_tensor", "AXIOM-TENSOR"
    CRE = "cre", "CRE"
    FQNM = "fqnm", "FQNM"
    QNTA = "qnta", "QNTA"


class WaiverType(models.TextChoices):
    NONE = "none", "No waiver"
    FULL = "full", "Full waiver"
    PARTIAL = "partial", "Partial waiver"


class EvaluationPackage(models.TextChoices):
    COMPUTE = "ALPHA Compute Bottleneck Assessment", "ALPHA Compute Bottleneck Assessment"
    CORE = "ALPHA Core Runtime Fit Assessment", "ALPHA Core Runtime Fit Assessment"
    COMBINED = "Combined ALPHA Evaluation", "Combined ALPHA Evaluation"


class Evaluation(BaseModel):
    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.CASCADE, related_name="evaluations"
    )
    lead_name = models.CharField(max_length=255, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")
    pkg = models.CharField(
        max_length=64, choices=EvaluationPackage.choices, default=EvaluationPackage.COMPUTE
    )
    status = models.CharField(
        max_length=12, choices=EvaluationStatus.choices, default=EvaluationStatus.PROPOSED
    )
    kpis = models.JSONField(default=list, blank=True)
    # Captured when the evaluation is requested (dashboard's optional fields).
    scope = models.TextField(blank=True, default="")
    fee = models.CharField(max_length=120, blank=True, default="")
    timeline = models.CharField(max_length=120, blank=True, default="")

    # v3.5 ALPHA Compute assessment governance. `fee` remains for compatibility;
    # these fields separate the standard fee, delegated AI decision, IWL override
    # and final customer-facing treatment. No numeric fee is invented by defaults.
    separate_workload = models.TextField(blank=True, default="")
    technical_route = models.CharField(max_length=24, choices=TechnicalRoute.choices, default=TechnicalRoute.NONE)
    eligibility_status = models.CharField(max_length=24, blank=True, default="unassessed")
    proof_status = models.CharField(max_length=24, blank=True, default="pending")
    standard_assessment_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ai_waiver_decision = models.CharField(max_length=16, choices=WaiverType.choices, default=WaiverType.NONE)
    waiver_type = models.CharField(max_length=16, choices=WaiverType.choices, default=WaiverType.NONE)
    waiver_percentage_or_amount = models.JSONField(default=dict, blank=True)
    waiver_reason = models.TextField(blank=True, default="")
    waiver_scope = models.CharField(max_length=255, blank=True, default="assessment_fee_only")
    waiver_expiry = models.DateTimeField(null=True, blank=True)
    iwl_override_status = models.CharField(max_length=24, blank=True, default="none")
    iwl_override_applied = models.BooleanField(default=False)
    iwl_override_reason = models.TextField(blank=True, default="")
    final_assessment_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    final_authority = models.CharField(max_length=24, blank=True, default="")
    fee_finalized_at = models.DateTimeField(null=True, blank=True)
    customer_fee_status = models.CharField(max_length=64, blank=True, default="paid_default_pending_quote")
    hardware_value_case = models.BooleanField(default=False)
    hardware_target = models.CharField(max_length=120, blank=True, default="")
    hardware_economics = models.TextField(blank=True, default="")
    hardware_sponsor = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Evaluation"
        verbose_name_plural = "Evaluations"

    def __str__(self) -> str:
        return f"Evaluation({self.lead_name or self.lead_id}, {self.status})"
