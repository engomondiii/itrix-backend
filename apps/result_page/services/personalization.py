"""Generalised, hypothesis-safe review personalization.

Personalization is configuration over decision/workload shape, not a company-name branch.
The 60-persona registry may contribute *internal hypothesis* vocabulary only when a
company was supplied by the user and the conversation materially matches one of that
account's roster entries. It never verifies identity, raises disclosure, changes journey
state, or exposes persona/lane identifiers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.personas.models import FunctionalFamily
from apps.personas.services.matcher import infer_family, match_company


@dataclass(frozen=True)
class ReviewPersonalization:
    kind: str = "generic"
    audience_label: str = "Technical decision-maker"
    focus: str = "computational efficiency and evidence"
    kpis: list[dict] = field(default_factory=list)
    diagnosis_titles: list[str] = field(default_factory=list)
    structural_hypothesis: str = ""


_FAMILY = {
    FunctionalFamily.AI_MODEL_SYSTEMS: {
        "audience": "AI model / research decision-maker",
        "focus": "model capability, experiment efficiency and measurable task validity",
        "diagnosis": [
            "Model-stage representation overhead",
            "Memory and data-movement pressure",
            "Latency / throughput constraint",
            "Task-validity and measurement boundary",
        ],
    },
    FunctionalFamily.CLOUD_INFRASTRUCTURE: {
        "audience": "Cloud / infrastructure decision-maker",
        "focus": "capacity, utilization, energy burden and fleet economics",
        "diagnosis": [
            "Capacity and utilization pressure",
            "Memory / movement overhead",
            "End-to-end latency constraint",
            "Instrumentation gap before architecture choice",
        ],
    },
    FunctionalFamily.SILICON_MEMORY_HARDWARE: {
        "audience": "Silicon / hardware architecture decision-maker",
        "focus": "workload-to-hardware fit, memory movement and execution-path utilization",
        "diagnosis": [
            "Workload-to-engine fit",
            "Memory-interface pressure",
            "Representation / layout overhead",
            "Execution-path utilization",
        ],
    },
    FunctionalFamily.RUNTIME_HPC_SIMULATION: {
        "audience": "Runtime / numerical-computing decision-maker",
        "focus": "runtime efficiency, numerical validity and delivery risk",
        "diagnosis": [
            "Runtime and conversion overhead",
            "Numerical / task-validity boundary",
            "Data movement and materialization",
            "Portability / delivery risk",
        ],
    },
    FunctionalFamily.STRATEGIC_PRODUCT_PARTNERSHIPS: {
        "audience": "Product / platform decision-maker",
        "focus": "product capability, deployment consequences and evidence needed for a decision",
        "diagnosis": [
            "Product capability constraint",
            "Deployment and integration boundary",
            "User-visible latency / energy consequence",
            "Evidence needed before a strategic decision",
        ],
    },
}

_GENERIC_KPIS = [
    {"label": "Task-validity baseline", "metric": "Freeze before comparing alternatives"},
    {"label": "Runtime / latency", "metric": "Measure on the same bounded workload"},
    {"label": "Memory and data movement", "metric": "Measure transformation/materialization overhead as well"},
    {"label": "Energy / infrastructure burden", "metric": "Include only where it is material to the workload"},
]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 4}


def _best_registry_persona(company: str, corpus: str):
    """Return one internal roster hypothesis only when the supplied context distinguishes it."""
    personas = match_company(company)
    if not personas:
        return None
    tokens = _tokens(corpus)
    ranked = []
    for persona in personas:
        searchable = " ".join(
            [
                persona.department,
                persona.primary_persona,
                persona.workload_environment,
                persona.trigger_event,
                persona.decision_lens,
                persona.desired_gain,
                persona.primary_kpi,
                " ".join(persona.supporting_kpis or []),
            ]
        ).lower()
        score = sum(1 for token in tokens if token in searchable)
        ranked.append((score, -int(persona.priority or 99), persona.persona_id, persona))
    ranked.sort(reverse=True)
    # Company alone is not enough to choose a department/persona. Require at least one
    # material workload/decision token from the conversation.
    return ranked[0][3] if ranked and ranked[0][0] > 0 else None


def _profile_from_family(family: str | None) -> ReviewPersonalization:
    cfg = _FAMILY.get(family)
    if not cfg:
        return ReviewPersonalization(kpis=list(_GENERIC_KPIS))
    return ReviewPersonalization(
        kind=str(family),
        audience_label=cfg["audience"],
        focus=cfg["focus"],
        diagnosis_titles=list(cfg["diagnosis"]),
        kpis=list(_GENERIC_KPIS),
        structural_hypothesis=(
            "Test one bounded workload to determine whether representation, data movement or repeated "
            "materialization creates avoidable burden before assuming additional hardware capacity or a "
            "different execution stack is the answer."
        ),
    )


def _profile_from_persona(persona) -> ReviewPersonalization:
    cfg = _FAMILY.get(persona.functional_family) or _FAMILY[FunctionalFamily.STRATEGIC_PRODUCT_PARTNERSHIPS]
    labels = [persona.primary_kpi, *(persona.supporting_kpis or [])]
    labels = [str(x).strip() for x in labels if str(x or "").strip()][:5]
    kpis = [
        {"label": label[:140], "metric": "Measure on the frozen representative workload"}
        for label in labels
    ] or list(_GENERIC_KPIS)
    boundary = " ".join(str(persona.boundary_waste_hypothesis or "").split()).strip()
    hypothesis = (
        f"A bounded hypothesis to test is whether {boundary[0].lower() + boundary[1:] if boundary else 'representation or boundary overhead'} "
        "creates avoidable execution burden. This roster entry is a hypothesis for framing, not a diagnosis or a verified fact about the visitor."
    )
    return ReviewPersonalization(
        kind=f"registry:{persona.functional_family}",
        audience_label=persona.primary_persona or cfg["audience"],
        focus=persona.decision_lens or persona.desired_gain or cfg["focus"],
        kpis=kpis,
        diagnosis_titles=list(cfg["diagnosis"]),
        structural_hypothesis=hypothesis,
    )


def _localized(profile: ReviewPersonalization, locale: str) -> ReviewPersonalization:
    """Localize controlled UI framing; dynamic source-derived terms fall back to English."""
    if not str(locale or "").lower().startswith("ko"):
        return profile
    audience = {
        "Technical decision-maker": "기술 의사결정자",
        "AI model / research decision-maker": "AI 모델 / 연구 의사결정자",
        "Cloud / infrastructure decision-maker": "클라우드 / 인프라 의사결정자",
        "Silicon / hardware architecture decision-maker": "실리콘 / 하드웨어 아키텍처 의사결정자",
        "Runtime / numerical-computing decision-maker": "런타임 / 수치 계산 의사결정자",
        "Product / platform decision-maker": "제품 / 플랫폼 의사결정자",
    }.get(profile.audience_label, profile.audience_label)
    metric_map = {
        "Freeze before comparing alternatives": "대안을 비교하기 전에 기준선을 고정",
        "Measure on the same bounded workload": "동일한 제한 워크로드에서 측정",
        "Measure transformation/materialization overhead as well": "변환/구체화 오버헤드도 함께 측정",
        "Include only where it is material to the workload": "워크로드에 실질적으로 중요한 경우에만 포함",
        "Measure on the frozen representative workload": "고정된 대표 워크로드에서 측정",
    }
    return ReviewPersonalization(
        kind=profile.kind,
        audience_label=audience,
        focus=profile.focus,
        kpis=[{**row, "metric": metric_map.get(str(row.get("metric", "")), str(row.get("metric", "")))} for row in profile.kpis],
        diagnosis_titles=profile.diagnosis_titles,
        structural_hypothesis=profile.structural_hypothesis,
    )


def for_snapshot(snapshot) -> ReviewPersonalization:
    corpus = snapshot.corpus
    profile = None
    if snapshot.company:
        persona = _best_registry_persona(snapshot.company, corpus)
        if persona is not None:
            profile = _profile_from_persona(persona)
    if profile is None:
        family, _confidence = infer_family(prompt=corpus, pressures=snapshot.pressure_areas)
        profile = _profile_from_family(family)
    return _localized(profile, getattr(snapshot, "locale", "en"))
