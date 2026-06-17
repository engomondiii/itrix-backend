"""
NDA detection.

Scans a visitor's free-text prompt for signals that they may be about to disclose
confidential or proprietary technical detail before an NDA is in place. The public
site asks visitors *not* to share confidential information pre-NDA; when this detector
fires, the immediate response surfaces a gentle NDA reminder and the lead is flagged
so the team knows to put an NDA in place early.

This is deliberately conservative and explainable (keyword/pattern based) — there is
no model dependency, so it runs identically whether or not the AI engine is enabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Phrases that suggest the visitor is sharing (or about to share) sensitive material.
_CONFIDENTIAL_SIGNALS: tuple[str, ...] = (
    "confidential",
    "proprietary",
    "trade secret",
    "under nda",
    "our source code",
    "internal benchmark",
    "unpublished",
    "patent pending",
    "our secret",
    "do not share",
    "not public",
    "internal only",
    "our architecture diagram",
    "our exact algorithm",
    "our exact implementation",
)

# Signals that the workload itself is sensitive IP (chip/runtime internals, etc.).
_SENSITIVE_DOMAIN_SIGNALS: tuple[str, ...] = (
    "our chip design",
    "our rtl",
    "our netlist",
    "our kernel implementation",
    "our solver internals",
    "our model weights",
    "our training data",
)

_WORD_BOUNDARY = "{}".format  # placeholder to keep linters calm; see _contains


def _contains(haystack: str, needle: str) -> bool:
    # Whole-phrase, case-insensitive, word-ish boundary match.
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, haystack, flags=re.IGNORECASE) is not None


@dataclass
class NDADetectionResult:
    nda_recommended: bool
    matched_signals: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "nda_recommended": self.nda_recommended,
            "matched_signals": self.matched_signals,
            "reason": self.reason,
        }


def detect_nda_signals(prompt: str | None) -> NDADetectionResult:
    """Inspect a prompt and decide whether an NDA reminder/flag is warranted."""
    text = (prompt or "").strip()
    if not text:
        return NDADetectionResult(nda_recommended=False)

    matched: list[str] = []
    for signal in (*_CONFIDENTIAL_SIGNALS, *_SENSITIVE_DOMAIN_SIGNALS):
        if _contains(text, signal):
            matched.append(signal)

    if matched:
        reason = (
            "The description references potentially confidential or proprietary "
            "material. An NDA should be in place before detailed technical exchange."
        )
        return NDADetectionResult(
            nda_recommended=True, matched_signals=matched, reason=reason
        )

    return NDADetectionResult(nda_recommended=False)
