"""Protection against direct and oracle-style extraction of eligibility logic."""
from __future__ import annotations

import re

_DIRECT = re.compile(
    r"\b(exact|detailed|full)\b.{0,50}\b(eligibility|selection|routing|transformation)\b.{0,40}\b(rule|logic|criteria|threshold|algorithm)\b|"
    r"\b(show|give|reveal|list|explain)\b.{0,50}\b(eligibility rules?|selection logic|decision boundary|thresholds?)\b",
    re.I | re.S,
)
_DERIVATIVE = re.compile(
    r"\b(?:eligible|ineligible)\b.{0,80}\b(?:hypothetical|workloads?|examples?|ten|batch|list)\b|"
    r"\b(?:rank|score|label|classify|binary|yes/no|threshold)\b.{0,100}\b(?:workloads?|examples?|axiom|cre|fqnm|eligib)\b|"
    r"\bno explanation\b.{0,80}\b(?:label|eligible|ineligible|score|rank)\b",
    re.I | re.S,
)
_PUBLIC_SAFE_BOUNDARY = re.compile(
    r"\b(?:public[- ]safe|public[- ]approved|high[- ]level)\b.{0,120}\b(?:boundary|distinction|difference|overview)\b|"
    r"\b(?:boundary|distinction|difference|overview)\b.{0,120}\b(?:public[- ]safe|public[- ]approved|high[- ]level)\b",
    re.I | re.S,
)
_EXPLICITLY_EXCLUDES_PROTECTED = re.compile(
    r"\b(?:do not|don't|without)\b.{0,80}\b(?:eligibility rules?|selection logic|implementation details?|"
    r"thresholds?|performance claims?|confidential (?:math(?:ematics)?|details?|logic))\b",
    re.I | re.S,
)


def is_probe(text: str) -> bool:
    raw = text or ""
    # A request explicitly limited to the approved public-safe boundary, while
    # expressly excluding eligibility/implementation detail, is the useful
    # alternative the oracle-probing policy itself promises. Do not refuse it.
    if _PUBLIC_SAFE_BOUNDARY.search(raw) and _EXPLICITLY_EXCLUDES_PROTECTED.search(raw):
        return False
    return bool(_DIRECT.search(raw) or _DERIVATIVE.search(raw))


def record(thread) -> int:
    state = dict(getattr(thread, "conversation_commitments", None) or {})
    risk = dict(state.get("protected_probe") or {})
    count = int(risk.get("count") or 0) + 1
    risk["count"] = count
    state["protected_probe"] = risk
    thread.conversation_commitments = state
    thread.save(update_fields=["conversation_commitments", "updated_at"])
    return count


def safe_reply(*, locale: str = "en") -> str:
    if (locale or "").lower().startswith("ko"):
        return (
            "보호된 적격성·선택 로직의 규칙, 점수, 임계값 또는 반복적인 이진 판정을 제공할 수는 없습니다. "
            "그런 출력은 반복·적응형 질의를 통해 의사결정 경계를 근사하는 데 사용될 수 있기 때문입니다. "
            "대신 공개 승인된 수준의 AXIOM·CRE·FQNM 차이와 평가에서 어떤 증거를 확인하는지는 설명할 수 있습니다."
        )
    return (
        "I can’t provide the protected eligibility/selection rules, scores, thresholds, or a sequence of "
        "binary labels that could be used to reconstruct them. Repeated or adaptive outputs can approximate "
        "a protected decision boundary even when the rules are not stated directly. I can still explain the "
        "approved public-safe distinctions among AXIOM, CRE and FQNM, or describe what evidence a controlled "
        "assessment would examine without exposing the selection logic."
    )
