"""Small fixed customer-safe responses used when deterministic safety controls fail."""

from __future__ import annotations

_GOVERNANCE_UNAVAILABLE_EN = (
    "I can’t safely complete that answer just now. Please try again in a moment."
)
_GOVERNANCE_UNAVAILABLE_KO = (
    "지금은 이 답변을 안전하게 완료할 수 없습니다. 잠시 후 다시 시도해 주세요."
)


def governance_unavailable(*, locale: str = "en") -> str:
    """Return approved fixed copy; never includes model output or exception detail."""
    return (
        _GOVERNANCE_UNAVAILABLE_KO
        if str(locale or "").lower().startswith("ko")
        else _GOVERNANCE_UNAVAILABLE_EN
    )
