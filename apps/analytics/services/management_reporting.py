"""Aggregate-safe management reporting for governed commercial progression.

This module deliberately stays inside the existing team-plane analytics subsystem. It
returns counts, distributions and rates only: no trust rationale, anti-abuse signals,
waiver reasoning, workload content or protected policy criteria leave the service.
"""

from __future__ import annotations

from collections import Counter
from statistics import median

from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationPackage, WaiverType
from apps.leads.models import ASTOPEngagement, ASTOPStage, Lead, TrustStatus
from apps.leads.services.commercial_progression import (
    alpha_compute_gate,
    alpha_core_gate,
    controlled_evaluation_proof_gate,
)
from apps.visitors.models import VisitorSession


_ACTIVE_ENTITLEMENT_STATUSES = {"active", "authorized", "enabled"}
_BLOCKING_REVOCATION_STATUSES = {"revoked", "revoking", "suspended", "blocked"}


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _normalised(value, *, fallback: str = "unattributed") -> str:
    text = str(value or "").strip()
    return text or fallback


def _lead_acquisition(lead: Lead) -> dict:
    return lead.acquisition_context if isinstance(lead.acquisition_context, dict) else {}


def _acquisition_summary(leads: list[Lead]) -> dict:
    visitors = list(VisitorSession.objects.all())
    traffic_by_source = Counter(_normalised(v.source_channel) for v in visitors)
    leads_by_source = Counter(
        _normalised(_lead_acquisition(lead).get("source_channel")) for lead in leads
    )

    traffic_campaigns = Counter(
        _normalised(v.campaign_content, fallback="unattributed") for v in visitors
    )
    lead_campaigns = Counter(
        _normalised(_lead_acquisition(lead).get("campaign_content"), fallback="unattributed")
        for lead in leads
    )

    linked_visitor_ids = {
        lead.review_session.visitor_session_id
        for lead in leads
        if lead.review_session_id
        and getattr(lead.review_session, "visitor_session_id", None) is not None
    }

    persona_channel = Counter()
    for lead in leads:
        if lead.persona_id is None:
            continue
        source = _normalised(_lead_acquisition(lead).get("source_channel"))
        persona_channel[(source, lead.persona.persona_id)] += 1

    return {
        "trafficBySource": dict(sorted(traffic_by_source.items())),
        "leadsBySource": dict(sorted(leads_by_source.items())),
        "trafficByCampaignContent": dict(sorted(traffic_campaigns.items())),
        "leadsByCampaignContent": dict(sorted(lead_campaigns.items())),
        "referralVisitorCount": sum(bool(str(v.referral_or_intro or "").strip()) for v in visitors),
        "referralLeadCount": sum(
            bool(str(_lead_acquisition(lead).get("referral_or_intro") or "").strip())
            for lead in leads
        ),
        "trustedIntroductionCount": sum(
            _lead_acquisition(lead).get("trusted_introduction_confirmed") is True
            for lead in leads
        ),
        "visitorToLead": {
            "visitorSessions": len(visitors),
            "convertedVisitorSessions": len(linked_visitor_ids),
            "conversionRate": _rate(len(linked_visitor_ids), len(visitors)),
        },
        "personaChannelRelationships": [
            {"sourceChannel": source, "personaId": persona_id, "count": count}
            for (source, persona_id), count in sorted(persona_channel.items())
        ],
    }


def _trust_summary(leads: list[Lead]) -> dict:
    counts = Counter(lead.trust_status for lead in leads)
    screened = sum(counts.get(status, 0) for status in (TrustStatus.PASS, TrustStatus.REVIEW, TrustStatus.REJECT))
    return {
        "pass": counts.get(TrustStatus.PASS, 0),
        "review": counts.get(TrustStatus.REVIEW, 0),
        "reject": counts.get(TrustStatus.REJECT, 0),
        "escalated": sum(bool(lead.escalated) for lead in leads),
        "screenedLeads": screened,
        "screeningCoverageRate": _rate(screened, len(leads)),
        "passRateAmongScreened": _rate(counts.get(TrustStatus.PASS, 0), screened),
    }


def _valid_ttfv_seconds(records: list[ASTOPEngagement]) -> list[int]:
    values: list[int] = []
    for record in records:
        start = record.authorized_install_at
        end = record.reproducible_value_at
        if start is None or end is None or end < start:
            continue
        values.append(int((end - start).total_seconds()))
    return values


def _ttfv_summary(records: list[ASTOPEngagement]) -> dict:
    values = _valid_ttfv_seconds(records)
    if not values:
        return {
            "validRecordCount": 0,
            "averageSeconds": None,
            "medianSeconds": None,
            "minSeconds": None,
            "maxSeconds": None,
        }
    return {
        "validRecordCount": len(values),
        "averageSeconds": round(sum(values) / len(values), 2),
        "medianSeconds": median(values),
        "minSeconds": min(values),
        "maxSeconds": max(values),
    }


def _governed_measured_value(record: ASTOPEngagement) -> bool:
    measured = record.measured_savings if isinstance(record.measured_savings, dict) else {}
    if not record.has_verified_value:
        return False
    if "value" not in measured or measured.get("value") is None:
        return False
    if not any(str(measured.get(key) or "").strip() for key in ("provenance", "source", "basis", "measurement_source")):
        return False
    return controlled_evaluation_proof_gate(record).allowed


def _astop_summary(records: list[ASTOPEngagement]) -> dict:
    stage_counts = Counter(record.stage for record in records)
    qualified_stages = {
        ASTOPStage.NDA_BRIEFING,
        ASTOPStage.CONTROLLED_EVALUATION,
        ASTOPStage.LO_DEPLOYMENT,
        ASTOPStage.VERIFY_EXPAND,
    }
    evaluation_stages = {
        ASTOPStage.CONTROLLED_EVALUATION,
        ASTOPStage.LO_DEPLOYMENT,
        ASTOPStage.VERIFY_EXPAND,
    }
    lo_stages = {ASTOPStage.LO_DEPLOYMENT, ASTOPStage.VERIFY_EXPAND}

    qualified = sum(record.stage in qualified_stages for record in records)
    evaluated = sum(record.stage in evaluation_stages for record in records)
    lo_reached = sum(record.stage in lo_stages for record in records)

    expansion_status = Counter()
    expansion_count = 0
    for record in records:
        expansion = record.expansion if isinstance(record.expansion, dict) else {}
        if not expansion:
            continue
        expansion_count += 1
        expansion_status[_normalised(expansion.get("status"), fallback="unspecified")] += 1

    return {
        "qualifiedProspects": qualified,
        "stageCounts": {
            ASTOPStage.IDENTIFY_QUALIFY: stage_counts.get(ASTOPStage.IDENTIFY_QUALIFY, 0),
            ASTOPStage.NDA_BRIEFING: stage_counts.get(ASTOPStage.NDA_BRIEFING, 0),
            ASTOPStage.CONTROLLED_EVALUATION: stage_counts.get(ASTOPStage.CONTROLLED_EVALUATION, 0),
            ASTOPStage.LO_DEPLOYMENT: stage_counts.get(ASTOPStage.LO_DEPLOYMENT, 0),
            ASTOPStage.VERIFY_EXPAND: stage_counts.get(ASTOPStage.VERIFY_EXPAND, 0),
            ASTOPStage.CLOSED: stage_counts.get(ASTOPStage.CLOSED, 0),
        },
        "qualifiedToEvaluationConversionRate": _rate(evaluated, qualified),
        "evaluationToLoConversionRate": _rate(lo_reached, evaluated),
        "verifiedValueCount": sum(record.has_verified_value for record in records),
        "governedMeasuredValueCount": sum(_governed_measured_value(record) for record in records),
        "ttfv": _ttfv_summary(records),
        "expansion": {
            "count": expansion_count,
            "byStatus": dict(sorted(expansion_status.items())),
        },
    }


def _entitlement_summary(records: list[ASTOPEngagement]) -> dict:
    now = timezone.now()
    status_counts = Counter(_normalised(record.entitlement_status, fallback="unset") for record in records)
    terms_status = Counter()
    rights_type = Counter()
    active = 0
    expired = 0
    revoked = 0
    blocked_or_suspended = 0
    for record in records:
        status = str(record.entitlement_status or "").strip().lower()
        revocation = str(record.revocation_status or "").strip().lower()
        is_expired = record.entitlement_expires_at is not None and record.entitlement_expires_at <= now
        scope = record.lo_scope if isinstance(record.lo_scope, dict) else {}
        terms = scope.get("governed_terms") if isinstance(scope.get("governed_terms"), dict) else {}
        terms_status[_normalised(terms.get("status"), fallback="missing")] += 1
        rights = terms.get("rights") if isinstance(terms.get("rights"), dict) else {}
        if rights.get("rights_type"):
            rights_type[_normalised(rights.get("rights_type"), fallback="unset")] += 1
        if is_expired:
            expired += 1
        if revocation == "revoked":
            revoked += 1
        elif revocation in _BLOCKING_REVOCATION_STATUSES:
            blocked_or_suspended += 1
        if (
            status in _ACTIVE_ENTITLEMENT_STATUSES
            and not is_expired
            and revocation not in _BLOCKING_REVOCATION_STATUSES
        ):
            active += 1

    return {
        "licenseOutExecutedCount": sum(record.lo_executed_at is not None for record in records),
        "entitlementStatus": dict(sorted(status_counts.items())),
        "activeEntitlements": active,
        "expiredEntitlements": expired,
        "revokedEntitlements": revoked,
        "blockedOrSuspendedEntitlements": blocked_or_suspended,
        # Aggregate-safe only: never emit account economics or provenance here.
        "governedLicenseOutTerms": {
            "byStatus": dict(sorted(terms_status.items())),
            "byRightsType": dict(sorted(rights_type.items())),
        },
    }


def _alpha_compute_summary(evaluations: list[Evaluation], records: list[ASTOPEngagement]) -> dict:
    compute = [evaluation for evaluation in evaluations if evaluation.pkg == EvaluationPackage.COMPUTE]
    current_qualified = 0
    for evaluation in compute:
        gate = alpha_compute_gate(
            evaluation.lead,
            separate_workload=evaluation.separate_workload,
            technical_route=evaluation.technical_route,
        )
        current_qualified += int(gate.allowed)

    ai_counts = Counter(evaluation.ai_waiver_decision or WaiverType.NONE for evaluation in compute)
    authority_counts = Counter(
        evaluation.final_authority
        for evaluation in compute
        if evaluation.fee_finalized_at is not None and evaluation.final_authority
    )
    verified_lead_ids = {record.lead_id for record in records if record.has_verified_value}
    assessed_verified_lead_ids = {
        evaluation.lead_id for evaluation in compute if evaluation.lead_id in verified_lead_ids
    }

    return {
        "qualifiedOpportunities": current_qualified,
        "assessmentsCreated": len(compute),
        "paidDefaultAssessments": sum(
            evaluation.customer_fee_status in {"paid_default_pending_quote", "paid"}
            for evaluation in compute
        ),
        "aiNoWaiver": ai_counts.get(WaiverType.NONE, 0),
        "aiPartialWaiver": ai_counts.get(WaiverType.PARTIAL, 0),
        "aiFullWaiver": ai_counts.get(WaiverType.FULL, 0),
        "iwlOverrides": sum(bool(evaluation.iwl_override_applied) for evaluation in compute),
        "noOverrideFinalizations": sum(
            evaluation.fee_finalized_at is not None and not evaluation.iwl_override_applied
            for evaluation in compute
        ),
        "finalAuthority": {
            "ai": authority_counts.get("ai", 0),
            "iwl": authority_counts.get("iwl", 0),
            "governance": authority_counts.get("governance", 0),
        },
        "astopVerifiedValueToAssessment": {
            "verifiedValueOpportunities": len(verified_lead_ids),
            "assessedOpportunities": len(assessed_verified_lead_ids),
            "conversionRate": _rate(len(assessed_verified_lead_ids), len(verified_lead_ids)),
        },
    }


def _alpha_core_summary(evaluations: list[Evaluation]) -> dict:
    compute = [evaluation for evaluation in evaluations if evaluation.pkg == EvaluationPackage.COMPUTE]
    pass_count = 0
    fail_count = 0
    for evaluation in compute:
        if alpha_core_gate(evaluation).allowed:
            pass_count += 1
        else:
            fail_count += 1
    return {
        "qualifiedCoreOpportunities": pass_count,
        "gatePass": pass_count,
        "gateFail": fail_count,
    }


def summary() -> dict:
    """Return the aggregate-safe internal management report."""
    leads = list(
        Lead.objects.select_related("review_session__visitor_session", "persona").all()
    )
    astop_records = list(ASTOPEngagement.objects.select_related("lead").all())
    evaluations = list(Evaluation.objects.select_related("lead").all())

    astop = _astop_summary(astop_records)
    entitlements = _entitlement_summary(astop_records)
    return {
        "acquisition": _acquisition_summary(leads),
        "trust": _trust_summary(leads),
        "astop": astop,
        "alphaCompute": _alpha_compute_summary(evaluations, astop_records),
        "alphaCore": _alpha_core_summary(evaluations),
        "commercial": entitlements,
        "customerSuccess": {
            "ttfv": astop["ttfv"],
            "verifiedValueCount": astop["verifiedValueCount"],
            "governedMeasuredValueCount": astop["governedMeasuredValueCount"],
            "deploymentEntitlement": entitlements,
            "expansion": astop["expansion"],
        },
        "dependencies": {
            "alphaCoreOpenedOpportunities": "P1-7: no authoritative Core opportunity-opening record exists yet.",
            "closedAstopHistoricalConversions": "ASTOPEngagement stores current stage only; closed rows cannot reconstruct prior funnel stages.",
            "explicitAiNoWaiverEvents": "ai_waiver_decision=none is also the schema default, so it cannot distinguish an explicit no-waiver decision from an untouched assessment.",
        },
    }
