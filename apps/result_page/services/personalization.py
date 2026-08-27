"""Safe persona-aware review framing.

Persona data changes emphasis, KPI vocabulary and the shape of a review. It never tells a
visitor which hidden persona was matched and never converts a company name into an assumed
fact. Company-specific language is activated only by the company/contact supplied on the
lead and by workload terms present in the safe conversation snapshot.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.personas.services.matcher import match_company


@dataclass(frozen=True)
class ReviewPersonalization:
    kind: str = "generic"
    audience_label: str = "Technical decision-maker"
    focus: str = "computational efficiency and evidence"
    kpis: list[dict] = field(default_factory=list)
    diagnosis_titles: list[str] = field(default_factory=list)
    structural_hypothesis: str = ""


def _has(text: str, *terms: str) -> bool:
    blob = (text or "").lower()
    return any(term.lower() in blob for term in terms)


def _company_is(company: str, name: str) -> bool:
    c = re.sub(r"[^a-z0-9]+", " ", (company or "").lower()).strip()
    return name.lower() in c.split() or c.startswith(name.lower())


def _registry_kpis(company: str, corpus: str) -> list[str]:
    """Use approved workbook fields as internal guidance without exposing a match."""
    personas = match_company(company)
    if not personas:
        return []
    tokens = set(re.findall(r"[a-z0-9]+", (corpus or "").lower()))
    ranked = []
    for persona in personas:
        searchable = " ".join(
            [
                persona.department,
                persona.primary_persona,
                persona.workload_environment,
                persona.trigger_event,
                persona.decision_lens,
            ]
        ).lower()
        score = sum(1 for token in tokens if len(token) >= 4 and token in searchable)
        ranked.append((score, -int(persona.priority or 99), persona))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = ranked[0][2]
    return [x for x in [best.primary_kpi, *(best.supporting_kpis or [])] if isinstance(x, str) and x.strip()]



def _localized(profile: ReviewPersonalization, locale: str) -> ReviewPersonalization:
    """Translate deterministic review framing, while leaving product/method names intact."""
    if not str(locale or "").lower().startswith("ko"):
        return profile
    maps = {
        "Spatial AI product / platform decision-maker": "Spatial AI 제품 / 플랫폼 의사결정자",
        "Mobile AI product / platform decision-maker": "모바일 AI 제품 / 플랫폼 의사결정자",
        "Agentic AI platform decision-maker": "에이전틱 AI 플랫폼 의사결정자",
        "Enterprise decision-maker": "엔터프라이즈 의사결정자",
        "Technical decision-maker": "기술 의사결정자",
        "spatial-AI capability scaling within energy, thermal and interaction-latency budgets": "에너지·열·상호작용 지연 예산 안에서 Spatial AI 기능을 확장하는 문제",
        "on-device AI capability within battery, thermal, memory and latency constraints": "배터리·열·메모리·지연 제약 안에서 온디바이스 AI 기능을 확장하는 문제",
        "agentic workflow cost and latency across repeated model, retrieval and tool boundaries": "반복되는 모델·검색·도구 경계 전반의 에이전틱 워크플로 비용과 지연",
        "the bounded workload and the decision criteria stated in the conversation": "대화에서 정한 제한된 워크로드와 의사결정 기준",
        "computational efficiency and evidence": "계산 효율성과 검증 근거",
    }
    title_map = {
        "Real-time perception workload scaling": "실시간 인지 워크로드 확장",
        "Continuous sensor-processing energy cost": "연속 센서 처리의 에너지 비용",
        "Memory movement and representation overhead": "메모리 이동 및 표현 오버헤드",
        "Edge-execution constraints": "엣지 실행 제약",
        "On-device inference scaling": "온디바이스 추론 확장",
        "Battery and thermal budget pressure": "배터리 및 열 예산 압력",
        "Memory-movement overhead": "메모리 이동 오버헤드",
        "Runtime / NPU boundary fit": "런타임 / NPU 경계 적합성",
        "Invocation-count pressure": "호출 횟수 압력",
        "Intermediate representation rebuilds": "중간 표현 재구성",
        "Retrieval / tool-call boundary overhead": "검색 / 도구 호출 경계 오버헤드",
        "Instrumentation gap before architecture choice": "아키텍처 선택 전 계측 공백",
    }
    kpi_map = {
        "Battery life per spatial-AI task": "Spatial AI 작업당 배터리 수명",
        "Sustained performance under thermal limits": "열 한계 내 지속 성능",
        "On-device capability per watt": "와트당 온디바이스 기능",
        "Latency consistency (p95/p99)": "지연 일관성 (p95/p99)",
        "Capability vs. energy budget": "기능 향상 대비 에너지 예산",
        "Useful on-device capability per watt": "와트당 유효 온디바이스 기능",
        "Sustained mobile inference latency": "지속 모바일 추론 지연",
        "Memory traffic per task": "작업당 메모리 트래픽",
        "Battery cost per AI task": "AI 작업당 배터리 비용",
        "End-to-end task cost": "엔드투엔드 작업 비용",
        "Invocations per completed task": "완료 작업당 호출 횟수",
        "Boundary / materialization overhead": "경계 / 구체화 오버헤드",
        "Task latency p95/p99": "작업 지연 p95/p99",
        "Task-validity baseline": "작업 유효성 기준선",
        "Runtime / latency": "런타임 / 지연",
        "Memory and data movement": "메모리 및 데이터 이동",
        "Energy / infrastructure burden": "에너지 / 인프라 부담",
    }
    metric_map = {
        "Compare at the same task-validity target": "동일한 작업 유효성 목표에서 비교",
        "Measure after the device reaches steady thermal conditions": "기기가 정상 열 상태에 도달한 뒤 측정",
        "Compare useful task capability against energy budget": "유효 작업 기능을 에너지 예산과 비교",
        "Measure tail latency, not only averages": "평균뿐 아니라 꼬리 지연도 측정",
        "Track whether capability can increase without proportional energy growth": "기능 증가가 에너지 증가에 비례하지 않는지 추적",
        "Compare at a fixed quality/task-validity target": "고정된 품질/작업 유효성 목표에서 비교",
        "Measure under representative thermal conditions": "대표적인 열 조건에서 측정",
        "Profile movement as well as arithmetic": "연산뿐 아니라 데이터 이동도 프로파일링",
        "Measure energy against the user-visible task outcome": "사용자 체감 작업 결과를 기준으로 에너지 측정",
        "Measure per completed agentic task, not per isolated call": "개별 호출이 아니라 완료된 에이전틱 작업당 측정",
        "Separate call count from per-call efficiency": "호출 횟수와 호출당 효율을 분리",
        "Profile representations rebuilt between pipeline steps": "파이프라인 단계 사이에서 재구성되는 표현을 프로파일링",
        "Capture long-tail effects across the whole workflow": "전체 워크플로의 장꼬리 효과를 포착",
        "Freeze before comparing alternatives": "대안을 비교하기 전에 기준선을 고정",
        "Measure on the same bounded workload": "동일한 제한 워크로드에서 측정",
        "Measure transformation/materialization overhead as well": "변환/구체화 오버헤드도 함께 측정",
        "Include only where it is material to the workload": "워크로드에 실질적으로 중요한 경우에만 포함",
        "Measure on the frozen representative workload": "고정된 대표 워크로드에서 측정",
    }
    hypothesis_map = {
        "apple_spatial": "추가 실리콘 용량이 답이라고 가정하기 전에, 선택한 Spatial AI 워크로드가 기존 실행 스택에 전달되는 표현 때문에 불필요한 데이터 이동이나 반복 작업이 발생하는지 검토합니다. 이는 검증할 가설이며 진단 결과가 아닙니다.",
        "samsung_mobile_ai": "추가 하드웨어 용량을 기본 해법으로 보기 전에, 제한된 모바일 AI 경로에서 표현과 데이터 이동이 불필요한 실행 부담을 만드는지 검증합니다. 이는 검증할 가설이며 진단 결과가 아닙니다.",
        "microsoft_agentic": "모델·검색·도구 단계의 반복 경계에서 구조가 버려졌다가 다시 구성되는지 검증하고, 패턴이 환원 불가능하면 대체 방식이 더 적절할 수 있다는 가능성을 유지합니다. 이는 검증할 가설이며 진단 결과가 아닙니다.",
    }
    return ReviewPersonalization(
        kind=profile.kind,
        audience_label=maps.get(profile.audience_label, profile.audience_label),
        focus=maps.get(profile.focus, profile.focus),
        kpis=[{
            **row,
            "label": kpi_map.get(str(row.get("label", "")), str(row.get("label", ""))),
            "metric": metric_map.get(str(row.get("metric", "")), str(row.get("metric", ""))),
        } for row in profile.kpis],
        diagnosis_titles=[title_map.get(x, x) for x in profile.diagnosis_titles],
        structural_hypothesis=hypothesis_map.get(profile.kind, profile.structural_hypothesis),
    )

def _for_snapshot_en(snapshot) -> ReviewPersonalization:
    corpus = snapshot.corpus
    company = snapshot.company
    registry_kpis = _registry_kpis(company, corpus)

    if _company_is(company, "apple") and _has(
        corpus, "spatial", "vision pro", "perception", "sensor fusion", "neural rendering", "3d", "ar interaction"
    ):
        return ReviewPersonalization(
            kind="apple_spatial",
            audience_label="Spatial AI product / platform decision-maker",
            focus="spatial-AI capability scaling within energy, thermal and interaction-latency budgets",
            kpis=[
                {"label": "Battery life per spatial-AI task", "metric": "Compare at the same task-validity target"},
                {"label": "Sustained performance under thermal limits", "metric": "Measure after the device reaches steady thermal conditions"},
                {"label": "On-device capability per watt", "metric": "Compare useful task capability against energy budget"},
                {"label": "Latency consistency (p95/p99)", "metric": "Measure tail latency, not only averages"},
                {"label": "Capability vs. energy budget", "metric": "Track whether capability can increase without proportional energy growth"},
            ],
            diagnosis_titles=[
                "Real-time perception workload scaling",
                "Continuous sensor-processing energy cost",
                "Memory movement and representation overhead",
                "Edge-execution constraints",
            ],
            structural_hypothesis=(
                "Before assuming more silicon capacity is the answer, examine whether the selected spatial-AI workload "
                "reaches the existing execution stack in a representation that creates avoidable movement or repeated work."
            ),
        )

    if _company_is(company, "samsung") and _has(
        corpus, "mobile", "galaxy", "on-device", "npu", "android", "battery", "thermal", "memory bandwidth"
    ):
        return ReviewPersonalization(
            kind="samsung_mobile_ai",
            audience_label="Mobile AI product / platform decision-maker",
            focus="on-device AI capability within battery, thermal, memory and latency constraints",
            kpis=[
                {"label": "Useful on-device capability per watt", "metric": "Compare at a fixed quality/task-validity target"},
                {"label": "Sustained mobile inference latency", "metric": "Measure under representative thermal conditions"},
                {"label": "Memory traffic per task", "metric": "Profile movement as well as arithmetic"},
                {"label": "Battery cost per AI task", "metric": "Measure energy against the user-visible task outcome"},
            ],
            diagnosis_titles=[
                "On-device inference scaling",
                "Battery and thermal budget pressure",
                "Memory-movement overhead",
                "Runtime / NPU boundary fit",
            ],
            structural_hypothesis=(
                "Examine one bounded mobile-AI path to determine whether representation and data movement are adding "
                "avoidable execution burden before treating additional hardware capacity as the default remedy."
            ),
        )

    if _company_is(company, "microsoft") and _has(
        corpus, "agent", "copilot", "tool call", "retrieval", "invocation", "model call", "pipeline"
    ):
        return ReviewPersonalization(
            kind="microsoft_agentic",
            audience_label="Agentic AI platform decision-maker",
            focus="agentic workflow cost and latency across repeated model, retrieval and tool boundaries",
            kpis=[
                {"label": "End-to-end task cost", "metric": "Measure per completed agentic task, not per isolated call"},
                {"label": "Invocations per completed task", "metric": "Separate call count from per-call efficiency"},
                {"label": "Boundary / materialization overhead", "metric": "Profile representations rebuilt between pipeline steps"},
                {"label": "Task latency p95/p99", "metric": "Capture long-tail effects across the whole workflow"},
            ],
            diagnosis_titles=[
                "Invocation-count pressure",
                "Intermediate representation rebuilds",
                "Retrieval / tool-call boundary overhead",
                "Instrumentation gap before architecture choice",
            ],
            structural_hypothesis=(
                "Test whether repeated boundaries between model, retrieval and tool steps discard structure that then has to be "
                "reconstructed, while keeping substitution as a valid alternative if the pattern proves irreducible."
            ),
        )

    # Registry KPI language is useful only as non-assertive vocabulary. Keep at most four.
    if registry_kpis:
        return ReviewPersonalization(
            kind="registry_guided",
            audience_label="Enterprise decision-maker",
            focus="the bounded workload and the decision criteria stated in the conversation",
            kpis=[{"label": label[:120], "metric": "Measure on the frozen representative workload"} for label in registry_kpis[:4]],
        )

    return ReviewPersonalization(
        kpis=[
            {"label": "Task-validity baseline", "metric": "Freeze before comparing alternatives"},
            {"label": "Runtime / latency", "metric": "Measure on the same bounded workload"},
            {"label": "Memory and data movement", "metric": "Measure transformation/materialization overhead as well"},
            {"label": "Energy / infrastructure burden", "metric": "Include only where it is material to the workload"},
        ]
    )


def for_snapshot(snapshot) -> ReviewPersonalization:
    return _localized(_for_snapshot_en(snapshot), getattr(snapshot, "locale", "en"))
