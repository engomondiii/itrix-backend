"""
Prohibited-language checker.

Scans generated text for the prohibited overclaims defined in the brand's claims
discipline (mirrors ``itrix-web/src/constants/disclosure.ts`` PROHIBITED_CLAIMS) plus a
few generic superlative/guarantee patterns. Used by the hallucination guard to scrub or
reject any model output before it reaches a visitor.

The point is conservative honesty: itriX never guarantees universal savings, perfect
accuracy, or "works for everything" — quantitative claims are deferred to a validated PoC.
"""

from __future__ import annotations

import re

# Exact prohibited claims from the frontend disclosure config.
PROHIBITED_CLAIMS = [
    "solves the AI energy crisis",
    "guarantees lower power",
    "reduces all AI costs",
    "guarantees perfect accuracy",
    "always faster",
    "works for every workload",
    "replaces your hardware",
]

# Generic risky patterns (guarantees / universals / unbounded superlatives).
_RISKY_PATTERNS = [
    r"\bguarantee(?:s|d)?\b",
    r"\b100%\b",
    r"\balways\b",
    r"\bnever fails?\b",
    r"\bevery (?:workload|use case|customer|problem)\b",
    r"\b(?:completely|fully) eliminat(?:e|es|ed)\b",
    r"\bunlimited\b",
]

_RISKY_RE = re.compile("|".join(_RISKY_PATTERNS), re.IGNORECASE)


def find_violations(text: str) -> list[str]:
    """Return a list of matched prohibited phrases / risky patterns in ``text``."""
    if not text:
        return []
    lowered = text.lower()
    violations = [claim for claim in PROHIBITED_CLAIMS if claim.lower() in lowered]
    violations += sorted({m.group(0).lower() for m in _RISKY_RE.finditer(text)})
    return violations


def contains_prohibited(text: str) -> bool:
    return bool(find_violations(text))


def scrub(text: str) -> str:
    """
    Soften prohibited language in-place so output stays publishable.

    Exact prohibited claims are removed; generic guarantee/superlative words are reworded
    to hedged equivalents.
    """
    if not text:
        return text
    out = text
    for claim in PROHIBITED_CLAIMS:
        out = re.sub(re.escape(claim), "may help with your specific workload", out, flags=re.IGNORECASE)
    replacements = {
        r"\bguarantees?\b": "aims to",
        r"\bguaranteed\b": "targeted",
        r"\b100%\b": "a high degree of",
        r"\balways faster\b": "often faster in eligible cases",
        r"\balways\b": "often",
        r"\bunlimited\b": "substantial",
    }
    for pattern, repl in replacements.items():
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out
