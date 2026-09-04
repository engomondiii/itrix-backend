"""Protection against direct, derivative and adaptive extraction of protected logic.

Only hashes and coarse risk categories are persisted. Raw probe bodies are not copied into
risk telemetry, so the control does not create a second store of potentially sensitive or
protected material.
"""
from __future__ import annotations

import hashlib
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
_CATEGORY_PATTERNS = {
    "binary": re.compile(r"\b(binary|yes/no|eligible|ineligible|label|classify)\b", re.I),
    "ranking": re.compile(r"\b(rank|ranking|score|sort|top\s+\d+)\b", re.I),
    "threshold": re.compile(r"\b(threshold|cutoff|decision boundary|minimum score)\b", re.I),
    "batch": re.compile(r"\b(batch|list|examples?|hypothetical|ten|twenty|100)\b", re.I),
    "logic": re.compile(r"\b(rule|logic|criteria|algorithm|eligibility|selection)\b", re.I),
}


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def fingerprint(text: str) -> str:
    return hashlib.sha256(_normal(text).encode()).hexdigest()


def categories(text: str) -> set[str]:
    return {name for name, pattern in _CATEGORY_PATTERNS.items() if pattern.search(text or "")}


def is_probe(text: str) -> bool:
    raw = text or ""
    if _PUBLIC_SAFE_BOUNDARY.search(raw) and _EXPLICITLY_EXCLUDES_PROTECTED.search(raw):
        return False
    return bool(_DIRECT.search(raw) or _DERIVATIVE.search(raw))


def is_history_probe(thread, text: str) -> bool:
    """Detect a sequence that can reconstruct the protected decision boundary.

    A single benign taxonomy question remains allowed. Repeated category combinations,
    repeated near-oracle requests, or a direct/derivative request are blocked.
    """
    if is_probe(text):
        return True
    if _PUBLIC_SAFE_BOUNDARY.search(text or "") and _EXPLICITLY_EXCLUDES_PROTECTED.search(text or ""):
        return False

    state = dict(getattr(thread, "conversation_commitments", None) or {})
    risk = dict(state.get("protected_probe") or {})
    previous_categories = set(risk.get("categories") or [])
    current = categories(text)
    if not current:
        return False
    hashes = list(risk.get("query_hashes") or [])
    fp = fingerprint(text)

    # Repeating a classification/ranking/threshold family after earlier probe activity is
    # adaptive extraction even if each sentence was softened enough to avoid _DERIVATIVE.
    oracle_categories = {"binary", "ranking", "threshold", "batch", "logic"}
    history_count = int(risk.get("count") or 0)
    if history_count >= 2 and current & oracle_categories:
        return True
    if fp in hashes and current & oracle_categories and history_count >= 1:
        return True
    if len((previous_categories | current) & oracle_categories) >= 3 and history_count >= 1:
        return True
    return False


def record(thread, text: str = "") -> int:
    state = dict(getattr(thread, "conversation_commitments", None) or {})
    risk = dict(state.get("protected_probe") or {})
    count = int(risk.get("count") or 0) + 1
    risk["count"] = count
    if text:
        hashes = list(risk.get("query_hashes") or [])
        fp = fingerprint(text)
        if fp not in hashes:
            hashes.append(fp)
        risk["query_hashes"] = hashes[-24:]
        risk["categories"] = sorted(set(risk.get("categories") or []) | categories(text))
    state["protected_probe"] = risk
    thread.conversation_commitments = state
    thread.save(update_fields=["conversation_commitments", "updated_at"])
    return count


def observe_safe(thread, text: str) -> None:
    """Record only coarse probe-adjacent history for future adaptive detection."""
    current = categories(text)
    if not current:
        return
    state = dict(getattr(thread, "conversation_commitments", None) or {})
    risk = dict(state.get("protected_probe") or {})
    hashes = list(risk.get("query_hashes") or [])
    fp = fingerprint(text)
    if fp not in hashes:
        hashes.append(fp)
    risk["query_hashes"] = hashes[-24:]
    risk["categories"] = sorted(set(risk.get("categories") or []) | current)
    risk["observed"] = int(risk.get("observed") or 0) + 1
    state["protected_probe"] = risk
    thread.conversation_commitments = state
    thread.save(update_fields=["conversation_commitments", "updated_at"])


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
