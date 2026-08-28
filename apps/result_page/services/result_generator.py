"""Governed My Review generation.

The artifact is downstream of the conversation that earned it.  Generation therefore
starts from the durable conversation snapshot (including accepted corrections and the
latest decision/evidence gaps), not from the first prompt.  A ResultPage is never marked
READY until its complete customer-safe schema has been validated and persisted.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.leads.models import PRODUCT_ROUTE_DISPLAY, Lead
from apps.result_page.models import ResultPage
from apps.result_page.services.conversation_snapshot import for_lead as conversation_snapshot
from apps.result_page.services.personalization import for_snapshot as personalize
from apps.result_page.services.proof_preview_builder import build_proof_preview
from apps.result_page.services.product_route_explainer import primary_technologies

logger = logging.getLogger("itrix")

REQUIRED_MIRROR_KEYS = (
    "statedFacts",
    "affectedDecision",
    "consequence",
    "boundedHypothesis",
    "unknowns",
    "confirmOrCorrect",
)


def _ko(snapshot) -> bool:
    return str(getattr(snapshot, "locale", "en") or "en").lower().startswith("ko")


def _t(snapshot, en: str, ko: str) -> str:
    return ko if _ko(snapshot) else en


def _clean(value: Any, *, limit: int = 2400) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _first_matching(lines: list[str], pattern: str) -> str:
    rx = re.compile(pattern, re.I)
    for line in reversed(lines):
        if rx.search(line):
            return _clean(line, limit=700)
    return ""


def _consequence(snapshot) -> str:
    candidate = _first_matching(
        snapshot.visitor_turns,
        r"\b(cost|latency|battery|thermal|power|energy|throughput|capacity|memory|bandwidth|reliab|deadline|budget|experience|scale)\b",
    )
    if candidate:
        return candidate
    return _t(
        snapshot,
        "The operational or business consequence has not yet been quantified; it should be measured against the same representative workload before a route is chosen.",
        "운영 또는 사업적 영향은 아직 정량화되지 않았습니다. 경로를 선택하기 전에 동일한 대표 워크로드에서 측정해야 합니다.",
    )


def _unknowns(snapshot) -> list[str]:
    corpus = snapshot.corpus.lower()
    items: list[str] = []
    if not re.search(r"\b(baseline|benchmark|current latency|current cost|current power|p95|p99)\b", corpus):
        items.append(_t(snapshot, "A frozen baseline and the evidence standard for judging any change.", "변화를 판단하기 위한 고정 기준선과 검증 기준."))
    if not re.search(r"\b(gpu|cpu|npu|tpu|fpga|device|cluster|runtime|framework|cloud|silicon|environment)\b", corpus):
        items.append(_t(snapshot, "The representative execution environment and software/hardware boundary.", "대표 실행 환경과 소프트웨어/하드웨어 경계."))
    if not snapshot.primary_decision:
        items.append(_t(snapshot, "The precise decision this review is intended to inform.", "이 리뷰가 지원해야 하는 정확한 의사결정."))
    if not snapshot.primary_gap:
        items.append(_t(snapshot, "Any instrumentation or evidence gaps that could prevent a fair comparison.", "공정한 비교를 방해할 수 있는 계측 또는 증거 공백."))
    items.append(_t(snapshot, "Which additional details can be shared safely at the current disclosure level.", "현재 공개 수준에서 안전하게 공유할 수 있는 추가 정보의 범위."))
    return items[:5]


def _structured_mirror(snapshot, profile) -> dict:
    """Build the canonical six-part, customer-readable mirror.

    When STR-03 already exists on the durable thread, prefer that confirmed/current
    artifact.  Otherwise construct the same six-part shape from the complete snapshot;
    this is the legacy questionnaire path where submitting the review itself is the
    explicit assessment action.
    """
    if snapshot.thread is not None:
        try:
            from apps.journey.constants import ARTIFACT_REFLECTION
            from apps.journey.models import Artifact

            artifact = (
                Artifact.objects.filter(
                    thread=snapshot.thread,
                    type=ARTIFACT_REFLECTION,
                    superseded_by__isnull=True,
                )
                .order_by("-version", "-created_at")
                .first()
            )
            payload = dict(getattr(artifact, "payload", None) or {}) if artifact else {}
            if payload.get("kind") == "strategic_problem_mirror" and all(payload.get(k) for k in REQUIRED_MIRROR_KEYS):
                return {
                    key: payload[key]
                    for key in (*REQUIRED_MIRROR_KEYS, "controls")
                    if key in payload
                }
        except Exception:  # noqa: BLE001
            logger.debug("Could not reuse reflection artifact for lead review", exc_info=True)

    facts = [
        _clean(turn, limit=650)
        for turn in snapshot.visitor_turns[-5:]
        if _clean(turn, limit=650)
    ]
    if snapshot.latest_correction and snapshot.latest_correction not in facts:
        facts.append(snapshot.latest_correction)
    facts = facts[-5:]

    decision = snapshot.primary_decision or _t(
        snapshot,
        "The exact organizational decision is not yet confirmed; the review should be used to clarify whether the next decision is about capacity, architecture, roadmap, deployment, or adoption.",
        "정확한 조직 의사결정은 아직 확인되지 않았습니다. 다음 결정이 용량, 아키텍처, 로드맵, 배포 또는 도입 중 무엇인지 먼저 명확히 해야 합니다.",
    )
    hypothesis = profile.structural_hypothesis or _t(
        snapshot,
        "One structural possibility worth examining is whether representation, data movement, or an execution boundary is adding avoidable work before additional compute capacity is assumed to be the answer. This is a hypothesis to test, not a finding.",
        "추가 계산 용량이 답이라고 가정하기 전에, 표현·데이터 이동·실행 경계가 불필요한 작업을 만드는지 검토할 가치가 있습니다. 이는 검증할 가설이며 진단 결과가 아닙니다.",
    )
    if not hypothesis.lower().startswith(("hypothesis", "one structural", "before")):
        hypothesis = f"Hypothesis — {hypothesis}"

    return {
        "statedFacts": facts or [_t(snapshot, "The review is based on the information supplied in this session.", "이 리뷰는 이번 세션에서 제공된 정보를 바탕으로 합니다.")],
        "affectedDecision": _clean(decision, limit=900),
        "consequence": _consequence(snapshot),
        "boundedHypothesis": _clean(hypothesis, limit=1000),
        "unknowns": _unknowns(snapshot),
        "confirmOrCorrect": _t(
            snapshot,
            "This is the current reading of your situation. Confirm it, refine it, or start again before it is treated as the basis for a strategic route.",
            "현재 상황에 대한 이해입니다. 전략적 경로의 근거로 사용하기 전에 확인하거나 수정하거나 처음부터 다시 시작할 수 있습니다.",
        ),
        "controls": [
            {"action": "confirm", "label": _t(snapshot, "This reflects my situation", "제 상황을 잘 반영합니다")},
            {"action": "refine", "label": _t(snapshot, "Refine this", "수정하기")},
            {"action": "restart", "label": _t(snapshot, "Start again", "처음부터 다시")},
        ],
    }


def _diagnosis(snapshot, profile) -> list[dict]:
    titles = list(profile.diagnosis_titles or [])
    if not titles:
        pressures = list(snapshot.pressure_areas or [])
        label = {
            "cost": _t(snapshot, "Compute-economics pressure", "계산 경제성 압력"),
            "speed": _t(snapshot, "Runtime / latency pressure", "런타임 / 지연 압력"),
            "energy": _t(snapshot, "Energy and thermal pressure", "에너지 및 열 압력"),
            "stability_accuracy": _t(snapshot, "Stability / accuracy pressure", "안정성 / 정확도 압력"),
            "memory_data_movement": _t(snapshot, "Memory and data-movement pressure", "메모리 및 데이터 이동 압력"),
            "hardware_utilization": _t(snapshot, "Execution / utilization pressure", "실행 / 활용 압력"),
            "architecture": _t(snapshot, "Architecture ceiling", "아키텍처 한계"),
        }
        titles = [label.get(p, str(p).replace("_", " ").title()) for p in pressures[:4]]
    if not titles:
        titles = [
            _t(snapshot, "Bounded workload characterization", "제한된 워크로드 특성"),
            _t(snapshot, "Representation / execution boundary", "표현 / 실행 경계"),
            _t(snapshot, "Evidence needed to discriminate causes", "원인을 구분하는 데 필요한 증거"),
        ]

    context = snapshot.latest_context or snapshot.workload or _t(snapshot, "the workload described in this review", "이 리뷰에서 설명한 워크로드")
    rows: list[dict] = []
    for i, title in enumerate(titles[:5]):
        if i == 0 and snapshot.latest_correction:
            observation = snapshot.latest_correction
        elif i == len(titles) - 1 and snapshot.primary_gap:
            observation = snapshot.primary_gap
        else:
            observation = context[:520]
        rows.append(
            {
                "title": _clean(title, limit=140),
                "observation": _clean(observation, limit=620),
                "interpretation": _t(
                    snapshot,
                    "This is a candidate boundary to test against the frozen workload and baseline; it is not yet a workload-specific finding.",
                    "고정된 워크로드와 기준선에서 검증할 후보 경계이며, 아직 워크로드별 확정 결과는 아닙니다.",
                ),
                "evidenceStatus": _t(snapshot, "Conversation-specific", "대화 기반") if observation else _t(snapshot, "General", "일반"),
            }
        )
    return rows


def _alpha_fit(snapshot, profile) -> str:
    focus = profile.focus or _t(snapshot, "the bounded workload and its decision criteria", "제한된 워크로드와 의사결정 기준")
    return _t(
        snapshot,
        f"For {focus}, itriX would first examine whether the selected workload reaches the existing execution stack in a computational representation that creates avoidable work. ALPHA Compute defines the representation hypothesis and can be evaluated on the existing software/hardware path; ALPHA Core is a separate, optional execution-validation path only when evidence justifies deeper implementation. No fit, no measurable advantage, or a conventional substitution being better are valid outcomes.",
        f"{focus}에 대해 itriX는 먼저 선택한 워크로드가 기존 실행 스택에 전달되는 계산 표현 때문에 불필요한 작업을 만드는지 확인합니다. ALPHA Compute는 표현 가설을 정의하고 기존 소프트웨어/하드웨어 경로에서 검증할 수 있습니다. ALPHA Core는 증거가 더 깊은 구현 검증을 정당화할 때만 별도로 검토하는 선택적 실행 검증 경로입니다. 적합하지 않음, 측정 가능한 이점 없음, 또는 기존 대체 방식이 더 나음도 유효한 결과입니다.",
    )


def _next_step(snapshot) -> str:
    if snapshot.thread is not None:
        try:
            from apps.conversations.services.engagement_state import recommendation_allowed
            if not recommendation_allowed(snapshot.thread):
                return _t(snapshot,
                    "Confirm or refine the Strategic Problem Mirror first. No product route or proof path is recommended until that interpretation is accepted or deliberately skipped.",
                    "먼저 Strategic Problem Mirror를 확인하거나 수정하세요. 그 해석이 확인되거나 의도적으로 건너뛸 때까지 제품 경로나 검증 경로를 추천하지 않습니다.")
        except Exception:  # noqa: BLE001
            pass
    if snapshot.evaluation_type == "poc":
        return _t(snapshot,
            "Define the explicitly selected proof-of-concept scope, baseline, KPIs and pass/partial/negative criteria before execution.",
            "명시적으로 선택한 PoC의 범위, 기준선, KPI 및 성공/부분/부정 결과 기준을 실행 전에 정의하세요.")
    if snapshot.evaluation_type in {"controlled_evaluation", "formal_evaluation"}:
        return _t(snapshot,
            "Freeze one representative workload, baseline, environment and validation criteria for the controlled evaluation.",
            "통제된 평가를 위해 하나의 대표 워크로드, 기준선, 환경 및 검증 기준을 고정하세요.")
    return _t(snapshot,
        "Freeze one representative workload, its baseline, target environment and decision criteria. Then decide whether a bounded controlled evaluation is warranted; a PoC is a separate choice, not an automatic next stage.",
        "하나의 대표 워크로드와 기준선, 대상 환경, 의사결정 기준을 고정하세요. 그 다음 제한된 통제 평가가 필요한지 판단합니다. PoC는 별도의 선택이며 자동 다음 단계가 아닙니다.")


def _validate_sections(sections: dict) -> None:
    mirror = sections.get("problemMirror")
    if not isinstance(mirror, dict) or not all(mirror.get(k) for k in REQUIRED_MIRROR_KEYS):
        raise ValueError("invalid_problem_mirror")
    if not isinstance(mirror.get("statedFacts"), list) or not mirror["statedFacts"]:
        raise ValueError("invalid_problem_mirror_facts")
    for key in ("diagnosis", "kpiPreview"):
        if not isinstance(sections.get(key), list) or not sections[key]:
            raise ValueError(f"invalid_{key}")
    if not _clean(sections.get("alphaFitSummary")):
        raise ValueError("invalid_alpha_fit")
    # Proof is optional by design. Never fail a review because no verified public proof
    # applies; omission is the correct behavior.
    for proof in sections.get("proofPreview") or []:
        if proof.get("disclosure") == "public" and not proof.get("reference"):
            raise ValueError("invalid_public_proof")
        if "2401.00000" in str(proof):
            raise ValueError("placeholder_proof")


class ResultGenerator:
    def generate_for_lead(
        self, lead: Lead, *, context: str = "public", use_ai: bool = True
    ) -> tuple[ResultPage, dict]:
        """Generate and atomically persist a complete My Review.

        Status moves PENDING -> READY only after schema validation and persistence.  Any
        caller exception must invoke ``mark_failed`` (the task/request wrappers do so), so
        an incomplete object can never be mistaken for a finished artifact.
        """
        snapshot = conversation_snapshot(lead)
        profile = personalize(snapshot)
        existing = ResultPage.objects.filter(lead=lead).first()
        version = (existing.artifact_version + 1) if existing and existing.generation_status == ResultPage.GenerationStatus.READY else (existing.artifact_version if existing else 1)
        ResultPage.objects.update_or_create(
            lead=lead,
            defaults={
                "generation_status": ResultPage.GenerationStatus.PENDING,
                "generation_error": "",
                "artifact_family": "my_review",
                "artifact_version": max(1, int(version or 1)),
                "locale": snapshot.locale,
            },
        )

        sections = {
            "problemMirror": _structured_mirror(snapshot, profile),
            "diagnosis": _diagnosis(snapshot, profile),
            "alphaFitSummary": _alpha_fit(snapshot, profile),
            "kpiPreview": list(profile.kpis or []),
            "proofPreview": build_proof_preview(
                product_route=lead.product_route,
                tier=lead.tier,
                context=context,
                workload_text=snapshot.corpus,
            ),
            "recommendedNextStep": _next_step(snapshot),
        }

        report = {"used_ai": False, "chunk_count": 0, "governance_status": "deterministic"}
        if use_ai:
            self._bounded_ai_enrichment(lead, snapshot, sections, report, context=context)

        _validate_sections(sections)
        mirror = sections["problemMirror"]
        problem_text = " ".join(
            [
                " ".join(mirror.get("statedFacts") or []),
                _clean(mirror.get("affectedDecision")),
                _clean(mirror.get("consequence")),
            ]
        ).strip()

        # Keep internal route/scoring fields for the cockpit, but the client serializer
        # intentionally omits them.
        defaults = {
            "tier": lead.tier,
            "score_breakdown": lead.score_breakdown,
            "product_route": PRODUCT_ROUTE_DISPLAY.get(lead.product_route, "ALPHA Compute"),
            "license_pathway": "",  # commercial pathway is not a My Review display field
            "primary_technologies": primary_technologies(lead.product_route),
            "problem_mirror": problem_text,
            "problem_mirror_structured": mirror,
            "persona_context": {
                "audience": profile.audience_label,
                "focus": profile.focus,
                # kind is deliberately not a hidden persona id/score; it is nevertheless
                # kept server-side and omitted by the public serializer.
                "kind": profile.kind,
            },
            "diagnosis": sections["diagnosis"],
            "alpha_fit_summary": _clean(sections["alphaFitSummary"], limit=5000),
            "kpi_preview": sections["kpiPreview"],
            "proof_preview": sections["proofPreview"],
            "recommended_next_step": _clean(sections["recommendedNextStep"], limit=3000),
            "used_ai": bool(report.get("used_ai")),
            "generation_status": ResultPage.GenerationStatus.READY,
            "generation_error": "",
            "artifact_family": "my_review",
            "artifact_version": max(1, int(version or 1)),
            "locale": snapshot.locale,
        }
        with transaction.atomic():
            result_obj, _ = ResultPage.objects.update_or_create(lead=lead, defaults=defaults)

        return result_obj, report

    def _bounded_ai_enrichment(self, lead, snapshot, sections: dict, report: dict, *, context: str) -> None:
        """Allow governed AI to enrich prose without replacing conversation truth/schema.

        The full safe conversation is the prompt.  Only text fields that can be safely
        validated are accepted; the canonical mirror, KPI selection and persona-specific
        diagnosis remain deterministic so malformed JSON can never reach the page.
        """
        try:
            from django.conf import settings

            if getattr(settings, "ENABLE_AGENTS", False):
                from apps.agents.services.context import AgentContext, PLANE_PUBLIC
                from apps.agents.services.runtime import run_diagnosis

                out = run_diagnosis(
                    AgentContext(
                        lead_id=str(lead.id),
                        prompt=snapshot.corpus or snapshot.first_prompt,
                        pressures=list(snapshot.pressure_areas or []),
                        product_route=lead.product_route,
                        license_pathway=None,
                        tier=lead.tier,
                        plane=PLANE_PUBLIC,
                        context_label="result_page",
                        extra=snapshot.as_agent_extra(),
                    )
                )
                report.update(
                    used_ai=bool(out.used_ai),
                    chunk_count=len(out.chunk_ids or []),
                    governance_status=out.governance_status,
                )
                if out.governance_status == "auto_approved":
                    payload = out.payload or {}
                    alpha = payload.get("alphaFitSummary")
                    if isinstance(alpha, str) and 40 <= len(alpha) <= 5000:
                        # Keep the canonical product boundary even if model prose drifts.
                        from apps.conversations.services.response_policy import enforce as apply_response_policy

                        sections["alphaFitSummary"] = apply_response_policy(
                            alpha,
                            thread=snapshot.thread,
                        )
            elif getattr(settings, "ENABLE_AI_ENGINE", False):
                # Compatibility path still uses the full snapshot, never the opening prompt.
                from apps.ai_engine.services.rag_pipeline import run_rag
                from apps.conversations.services.response_policy import enforce as apply_response_policy

                rag = run_rag(
                    prompt=snapshot.corpus or snapshot.first_prompt,
                    product_route=lead.product_route,
                    license_pathway=None,
                    tier=lead.tier,
                    pressures=list(snapshot.pressure_areas or []),
                    context=context,
                )
                report.update(used_ai=rag.used_ai, chunk_count=len(rag.chunks or []), governance_status="compat")
                alpha = (rag.partial or {}).get("alphaFitSummary")
                if isinstance(alpha, str) and 40 <= len(alpha) <= 5000:
                    sections["alphaFitSummary"] = apply_response_policy(alpha, thread=snapshot.thread)
        except Exception:  # noqa: BLE001
            logger.exception("Governed My Review enrichment failed; deterministic review retained")

    @staticmethod
    def mark_failed(lead: Lead, exc: Exception | str) -> ResultPage:
        """Persist a recoverable FAILED state; never expose raw exception text to clients."""
        obj, _ = ResultPage.objects.update_or_create(
            lead=lead,
            defaults={
                "generation_status": ResultPage.GenerationStatus.FAILED,
                "generation_error": _clean(exc, limit=1200),
            },
        )
        return obj

    def build_client_page(self, lead: Lead, *, context: str = "public", nda_signed: bool = False) -> dict:
        """Return an already-complete review; this path never generates or polls AI."""
        from apps.result_page.serializers import ResultPageSerializer

        result_obj = ResultPage.objects.filter(
            lead=lead,
            generation_status=ResultPage.GenerationStatus.READY,
        ).first()
        if result_obj is None:
            raise ResultPage.DoesNotExist("review_not_ready")
        return dict(ResultPageSerializer(result_obj).data)


def generate_result_for_lead(lead: Lead, **kwargs):
    return ResultGenerator().generate_for_lead(lead, **kwargs)


def emit_pitch_room_artifact(lead, page: dict | None = None):
    """Backward-compatible in-thread artifact helper; My Review is the primary artifact."""
    try:
        from apps.conversations.models import Thread
        from apps.journey.constants import ARTIFACT_PITCH_ROOM
        from apps.journey.services import artifacts

        thread = Thread.objects.filter(lead=lead).order_by("-last_activity_at").first()
        if thread is None:
            return None
        return artifacts.generate(thread, ARTIFACT_PITCH_ROOM, payload=page or None, force=True)
    except Exception:  # noqa: BLE001
        logger.debug("pitch-room artifact not emitted", exc_info=True)
        return None
