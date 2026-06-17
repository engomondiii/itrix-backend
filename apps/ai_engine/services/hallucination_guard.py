"""
Hallucination guard.

Final safety pass over any AI-generated, visitor-facing text. It:

* removes / softens prohibited language (claims discipline), and
* checks that the text is grounded — i.e. doesn't assert specific quantitative results
  (e.g. "40% faster", "3x cheaper") that aren't supported by retrieved evidence.

If unsupported quantitative claims are present, they're hedged rather than published. The
guard returns the cleaned text plus a report of what it changed, so callers can log it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.ai_engine.services.prohibited_language_checker import find_violations, scrub

# Specific numeric performance claims, e.g. "40% faster", "3x lower", "halves cost".
_QUANT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s?(?:%|x)|\bhalv(?:e|es|ed)\b|\bdoubl(?:e|es|ed)\b|\btripl(?:e|es|ed)\b)",
    re.IGNORECASE,
)


@dataclass
class GuardReport:
    text: str
    prohibited_removed: list[str] = field(default_factory=list)
    quant_hedged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.prohibited_removed or self.quant_hedged)


def _has_supporting_evidence(claim: str, evidence: str) -> bool:
    """True if the specific numeric token appears in the retrieved evidence text."""
    token = claim.strip().lower()
    return token in (evidence or "").lower()


def guard(text: str, *, evidence: str = "") -> GuardReport:
    """Clean ``text`` for public display, hedging unsupported quantitative claims."""
    if not text:
        return GuardReport(text=text)

    prohibited = find_violations(text)
    cleaned = scrub(text)

    hedged: list[str] = []
    for match in _QUANT_RE.finditer(cleaned):
        token = match.group(0)
        if not _has_supporting_evidence(token, evidence):
            hedged.append(token)

    # Hedge unsupported numeric claims by appending a qualifier the first time.
    if hedged:
        cleaned = re.sub(
            _QUANT_RE,
            lambda m: (
                m.group(0)
                if _has_supporting_evidence(m.group(0), evidence)
                else "potential improvements"
            ),
            cleaned,
        )

    return GuardReport(text=cleaned.strip(), prohibited_removed=prohibited, quant_hedged=hedged)


def is_safe(text: str, *, evidence: str = "") -> bool:
    """Quick boolean: would the guard need to change anything?"""
    return not guard(text, evidence=evidence).changed
