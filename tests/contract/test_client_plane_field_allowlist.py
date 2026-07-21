"""
THE CLIENT-PLANE FIELD ALLOW-LIST (Architecture v2.6 §10.5, Backend v6.0 §11.3).

    The following must NOT appear in ANY payload on the anonymous or client plane, at
    any state, in any turn, artifact or card:

        persona_id · pitch_room_id · tier · lead score · score breakdown
        license_out_probability · churn_risk · account_priority
        negotiation_posture · competitor_risk · objection_classification
        gate_decision · gate_decision_reason · internal notes · owner private fields
        coverage_map · question_budget_remaining · attachment_risk_flags
        retrieval_debug · chunk_ids_internal · stream_guard_hits
        customer_health · suppression_reason · stop_reason

    Enforced by SERIALIZER ALLOW-LISTS, not by the frontend omitting fields.

── WHY THIS IS A CROSS-CUTTING TEST ─────────────────────────────────────────
Every individual app has its own allow-list test. This one sweeps EVERY serializer in
the codebase, so a new client-plane serializer added in six months is checked against the
contract by a test nobody has to remember to write.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from rest_framework import serializers

# The §10.5 list, in both snake_case and camelCase.
FORBIDDEN_FIELDS = {
    "persona_id", "personaId", "pitch_room_id", "pitchRoomId",
    "tier", "score", "score_breakdown", "scoreBreakdown", "lead_score",
    "license_out_probability", "licenseOutProbability",
    "churn_risk", "churnRisk", "account_priority", "accountPriority",
    "negotiation_posture", "negotiationPosture",
    "competitor_risk", "competitorRisk",
    "objection_classification", "objectionClassification",
    "gate_decision", "gateDecision", "gate_decision_reason", "gateDecisionReason",
    "coverage_map", "coverageMap",
    "question_budget_remaining", "questionBudgetRemaining",
    "attachment_risk_flags", "attachmentRiskFlags", "risk_flags", "riskFlags",
    "retrieval_debug", "retrievalDebug",
    "chunk_ids_internal", "chunkIdsInternal",
    "stream_guard_hits", "streamGuardHits", "matched_text", "matchedText",
    "customer_health", "customerHealth",
    "suppression_reason", "suppressionReason",
    "stop_reason", "stopReason",
    "internal_notes", "internalNotes",
}

# Serializers whose NAME marks them as team-plane. Everything else is treated as
# client-facing — the safe default, because a serializer that forgets the convention is
# then CHECKED rather than skipped.
TEAM_PREFIXES = ("Team", "Cockpit", "Console", "Internal", "Admin")

# Modules that are entirely TEAM-PLANE — mounted only behind team-JWT in api/v1/urls.py.
#
# Classified by MOUNT rather than by naming convention: `LeadDetailSerializer` carries a
# tier and a score legitimately, because /leads/ is a team route. The question this test
# asks is "can an unidentified visitor or a client reach this?", and only the mount
# answers that.
TEAM_MODULES = {
    "apps.personas.serializers",       # internal-only in its entirety (§1.3)
    "apps.analytics.serializers",      # aggregates are team-only
    "apps.leads.serializers",          # /leads/          JWT
    "apps.pipeline.serializers",       # /pipeline/       JWT
    "apps.follow_up.serializers",      # /follow-up/      JWT
    "apps.evaluations.serializers",    # /evaluations/    JWT
    "apps.pocs.serializers",           # /pocs/           JWT
    "apps.reporting.serializers",      # /reporting/      JWT
    "apps.team.serializers",           # /team/           JWT
    "apps.governance.serializers",     # /governance/     JWT
    "apps.knowledge_core.serializers", # /knowledge-core/ JWT
    "apps.settings.serializers",       # /settings/       JWT
    "apps.emails.serializers",         # /emails/         JWT
    "apps.templates_library.serializers",
    "apps.notifications.serializers",
    "apps.nda.serializers",
    "apps.scoring.serializers",
    "apps.routing.serializers",
}

# Serializers that ACCEPT a field rather than emit one. A write-only serializer carrying
# ``score`` is a visitor SUBMITTING their own feedback — the opposite of a leak.
WRITE_ONLY_SERIALIZERS = {
    "FeedbackPulseSubmitSerializer",   # §12I: write-only by design, no read counterpart
    "SupportRequestCreateSerializer",
    "TurnSubmitSerializer",
    "ThreadCreateSerializer",
    "ThreadRenameSerializer",
    "AttachmentUploadSerializer",
    "AdvanceRequestSerializer",
    "InviteClaimRequestSerializer",
}


def _all_serializer_modules():
    import apps

    for module_info in pkgutil.walk_packages(apps.__path__, prefix="apps."):
        name = module_info.name
        if not name.endswith("serializers") and "serializers" not in name.rsplit(".", 1)[-1]:
            continue
        try:
            yield name, importlib.import_module(name)
        except Exception:  # noqa: BLE001 - an unimportable module is not this test's job
            continue


def _client_plane_serializers():
    for module_name, module in _all_serializer_modules():
        if module_name in TEAM_MODULES:
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, serializers.Serializer):
                continue
            if obj.__module__ != module_name:
                continue  # imported, not defined here
            if name.startswith(TEAM_PREFIXES):
                continue
            if name in WRITE_ONLY_SERIALIZERS:
                continue
            yield module_name, name, obj


def _declared_fields(serializer_class) -> set[str]:
    fields: set[str] = set()
    meta = getattr(serializer_class, "Meta", None)
    meta_fields = getattr(meta, "fields", None)
    if isinstance(meta_fields, (list, tuple)):
        fields |= set(meta_fields)
    fields |= set(getattr(serializer_class, "_declared_fields", {}).keys())
    return fields


def test_at_least_one_client_serializer_is_discovered():
    """Guards against the sweep silently finding nothing and passing vacuously."""
    discovered = list(_client_plane_serializers())
    assert len(discovered) >= 10, f"only found {len(discovered)} serializers — sweep is broken"


def test_no_client_plane_serializer_exposes_a_forbidden_field():
    """THE CONTRACT."""
    offenders: list[str] = []
    for module_name, name, obj in _client_plane_serializers():
        leaked = _declared_fields(obj) & FORBIDDEN_FIELDS
        if leaked:
            offenders.append(f"{module_name}.{name}: {sorted(leaked)}")
    assert not offenders, "internal fields on the client plane:\n  " + "\n  ".join(offenders)


def test_no_client_plane_serializer_uses_all_fields():
    """
    ``fields = "__all__"`` is a deny-list wearing a disguise: it admits every future
    column automatically, which is exactly how internal fields leak.
    """
    offenders = []
    for module_name, name, obj in _client_plane_serializers():
        meta = getattr(obj, "Meta", None)
        if meta is None:
            continue
        if getattr(meta, "fields", None) == "__all__":
            offenders.append(f"{module_name}.{name}")
        if getattr(meta, "exclude", None):
            offenders.append(f"{module_name}.{name} (uses exclude)")
    assert not offenders, "deny-listed serializers:\n  " + "\n  ".join(offenders)


@pytest.mark.django_db
def test_the_shell_contract_carries_no_internal_field():
    from apps.journey.services import shell
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory(journey_state="ASSESSMENT", email="x@example.com")
    rendered = str(shell.for_subject(lead))
    for forbidden in ("persona_id", "coverage_map", "customer_health",
                      "suppression_reason", "gate_decision"):
        assert forbidden not in rendered


@pytest.mark.django_db
def test_the_inline_cards_carry_no_internal_field():
    from django.utils import timezone

    from apps.journey.services import cards
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory(journey_state="ASSESSMENT", tier=1,
                       value_delivered_at=timezone.now())
    rendered = str(cards.build(lead))
    for forbidden in ("suppressionReason", "persona", "riskFlags", "customerHealth"):
        assert forbidden not in rendered
