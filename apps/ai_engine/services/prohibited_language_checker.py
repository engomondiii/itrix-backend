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

# Output-style substitutions only. Product/technology definitions are intentionally NOT
# hardcoded here; factual doctrine must come from the retrieved knowledge corpus.
CANONICAL_SUBSTITUTIONS = [
    (r"\bmagic\b", "engineered"),
    (r"\bsilver bullet\b", "a strong potential fit"),
    (r"\bcure[- ]?all\b", "broadly applicable approach"),
    (r"\bbest[- ]?in[- ]?class\b", "well-suited"),
    (r"\bworld[- ]?class\b", "high-quality"),
    (r"\bindustry[- ]?leading\b", "competitive"),
    (r"\brevolutionary\b", "novel"),
    (r"\bbreakthrough\b", "advance"),
    (r"\bcheaper than\b", "potentially more cost-effective than, pending evaluation,"),
    (r"faster than (?:the )?competition", "potentially faster in eligible cases"),
]

# Phrases that are HARD-BLOCKED (never scrubbed away silently, always require human
# review) — quantified performance/commercial claims.
#
# IMPORTANT: the methodology phrase "benchmarked against an agreed baseline" is NOT a
# performance claim and appears naturally in ALPHA's proof discipline.  Treating the
# words "benchmarked against" themselves as a hard block caused ordinary, grounded
# product explanations (for example "Go deeper on ALPHA Compute") to be replaced by
# the indefinite specialist-review notice.  Quantified comparisons remain blocked here;
# named-competitor comparisons are separately blocked by the stream guard.
HARD_BLOCK_PATTERNS = [
    r"\d+\s?x faster",
    r"\d+\s?x (?:cheaper|less energy|lower cost)",
    r"\d+%\s+(?:faster|cheaper|less energy|lower cost)",
]

# Guarantee handling is intentionally contextual.  A blanket lexical substitution turns
# harmless refusals/discussion ("a blanket guarantee", "cannot guarantee", "guarantees
# do not transfer") into malformed prose.  These patterns describe affirmative outcome
# assertions that must still be governed.
_AFFIRMATIVE_GUARANTEE_PATTERNS = [
    r"\b(?:we|i|you|they)\s+(?:will\s+)?guarantee\b",
    (
        r"\b(?:it|this|that|itri[xX]|alpha(?:\s+(?:compute|core))?|astop|"
        r"(?:the|our|this|that)\s+"
        r"(?:product|system|platform|technology|solution|service|software|hardware))"
        r"\s+(?:(?:will|does)\s+guarantee|guarantees)\b"
    ),
    r"\b(?:is|are|was|were|will be)\s+guaranteed\b",
    r"\b(?:is|are)\s+(?:a|the)\s+(?:blanket\s+)?guarantee\b",
    (
        r"\bguaranteed\s+(?:performance|results?|savings?|costs?|accuracy|outcomes?|"
        r"improvements?|execution|uptime|returns?|benefits?|figures?)\b"
    ),
]

# The adjective form can legitimately appear before the refusal arrives in the sentence,
# so it needs a small, explicit safe-context exception.  We keep this deliberately narrow:
# it recognizes refusals, not affirmative claims with a distant negation.
_SAFE_GUARANTEED_PATTERNS = [
    (
        r"\b(?:cannot|can't|can not|won't|will not|not able to|unable to)\s+"
        r"(?:reasonably\s+|credibly\s+|responsibly\s+)?"
        r"(?:provide|offer|give|promise|claim)\s+guaranteed\b"
    ),
    (
        r"\bguaranteed\b[^.!?;]{0,100}\b(?:is|are)\s+not\s+"
        r"(?:something|anything)\b[^.!?;]{0,100}\b"
        r"(?:provide|offer|give|promise|claim)\b"
    ),
    (
        r"\bguaranteed\b[^.!?;]{0,100}\b(?:cannot|can't|can not|won't|will not)\s+"
        r"be\s+(?:provided|offered|given|promised|claimed)\b"
    ),
]

_AFFIRMATIVE_GUARANTEE_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _AFFIRMATIVE_GUARANTEE_PATTERNS),
    re.IGNORECASE,
)
_SAFE_GUARANTEED_RES = [
    re.compile(pattern, re.IGNORECASE) for pattern in _SAFE_GUARANTEED_PATTERNS
]

# Generic risky patterns (universals / unbounded superlatives). Guarantee assertions are
# handled separately above so safe negative/discussion uses are not treated as violations.
_RISKY_PATTERNS = [
    r"\b100%\b",
    r"\balways\b",
    r"\bnever fails?\b",
    r"\bevery (?:workload|use case|customer|problem)\b",
    r"\b(?:completely|fully) eliminat(?:e|es|ed)\b",
    r"\bunlimited\b",
]

_RISKY_RE = re.compile("|".join(_RISKY_PATTERNS), re.IGNORECASE)
_HARD_BLOCK_RE = re.compile("|".join(HARD_BLOCK_PATTERNS), re.IGNORECASE)


def _is_safe_guaranteed_match(text: str, start: int) -> bool:
    """Whether an adjective-form guarantee match is part of an explicit refusal."""
    for safe_re in _SAFE_GUARANTEED_RES:
        for match in safe_re.finditer(text):
            if match.start() <= start < match.end():
                return True
    return False


def _find_affirmative_guarantees(text: str) -> list[str]:
    """Return affirmative guarantee assertions, excluding explicit refusal contexts."""
    violations: list[str] = []
    for match in _AFFIRMATIVE_GUARANTEE_RE.finditer(text):
        if match.group(0).lower().startswith("guaranteed") and _is_safe_guaranteed_match(
            text, match.start()
        ):
            continue
        violations.append(match.group(0).lower())
    return violations


def find_violations(text: str) -> list[str]:
    """Return a list of matched prohibited phrases / risky patterns in ``text``."""
    if not text:
        return []
    lowered = text.lower()
    violations = [claim for claim in PROHIBITED_CLAIMS if claim.lower() in lowered]
    violations += sorted(set(_find_affirmative_guarantees(text)))
    violations += sorted({m.group(0).lower() for m in _RISKY_RE.finditer(text)})
    violations += sorted({m.group(0).lower() for m in _HARD_BLOCK_RE.finditer(text)})
    return violations


def has_hard_block(text: str) -> bool:
    """True if the text contains a pattern that must be human-reviewed (never auto-scrubbed)."""
    return bool(text and _HARD_BLOCK_RE.search(text))


def contains_prohibited(text: str) -> bool:
    return bool(find_violations(text))


_PLURAL_SUBJECT_GUARANTEE_RE = re.compile(
    r"\b(?P<subject>we|i|you|they)\s+(?P<will>will\s+)?guarantee\b",
    re.IGNORECASE,
)
_THIRD_PERSON_GUARANTEE_RE = re.compile(
    (
        r"\b(?P<subject>it|this|that|itri[xX]|alpha(?:\s+(?:compute|core))?|astop|"
        r"(?:the|our|this|that)\s+"
        r"(?:product|system|platform|technology|solution|service|software|hardware))"
        r"\s+(?:(?P<aux>will|does)\s+guarantee|guarantees)\b"
    ),
    re.IGNORECASE,
)
_PASSIVE_GUARANTEE_RE = re.compile(
    r"\b(?P<aux>is|are|was|were|will be)\s+guaranteed\b",
    re.IGNORECASE,
)
_NOUN_GUARANTEE_RE = re.compile(
    r"\b(?P<aux>is|are)\s+(?P<article>a|the)\s+(?P<modifier>blanket\s+)?guarantee\b",
    re.IGNORECASE,
)
_GUARANTEED_ADJECTIVE_RE = re.compile(
    (
        r"\bguaranteed(?=\s+(?:performance|results?|savings?|costs?|accuracy|outcomes?|"
        r"improvements?|execution|uptime|returns?|benefits?|figures?)\b)"
    ),
    re.IGNORECASE,
)


def _scrub_guaranteed_adjectives(text: str) -> str:
    """Soften only affirmative adjective-form guarantees; preserve explicit refusals."""
    safe_spans = [
        match.span()
        for safe_re in _SAFE_GUARANTEED_RES
        for match in safe_re.finditer(text)
    ]

    def replacement(match: re.Match) -> str:
        if any(start <= match.start() < end for start, end in safe_spans):
            return match.group(0)
        return "potential"

    return _GUARANTEED_ADJECTIVE_RE.sub(replacement, text)


def _scrub_affirmative_guarantees(text: str) -> str:
    """Turn affirmative guarantees into grammatical non-guarantees without touching refusals."""
    out = _scrub_guaranteed_adjectives(text)

    def plural_replacement(match: re.Match) -> str:
        subject = match.group("subject")
        if match.group("will"):
            return f"{subject} will not guarantee"
        return f"{subject} do not guarantee"

    def third_person_replacement(match: re.Match) -> str:
        subject = match.group("subject")
        aux = match.group("aux")
        if aux:
            return f"{subject} {aux.lower()} not guarantee"
        return f"{subject} does not guarantee"

    out = _PLURAL_SUBJECT_GUARANTEE_RE.sub(plural_replacement, out)
    out = _THIRD_PERSON_GUARANTEE_RE.sub(third_person_replacement, out)
    out = _PASSIVE_GUARANTEE_RE.sub(
        lambda match: f"{match.group('aux')} not guaranteed",
        out,
    )
    out = _NOUN_GUARANTEE_RE.sub(
        lambda match: (
            f"{match.group('aux')} not {match.group('article')} "
            f"{match.group('modifier') or ''}guarantee"
        ),
        out,
    )
    return out


def scrub(text: str) -> str:
    """
    Soften prohibited language in-place so output stays publishable.

    Exact prohibited claims are removed. Affirmative guarantee assertions are rewritten
    contextually; negative/refusal/discussion uses of "guarantee" remain untouched.
    """
    if not text:
        return text

    out = _scrub_affirmative_guarantees(text)

    # Exact guarantee claims are normally removed by the contextual pass above. Keeping
    # the exact-claim pass afterwards preserves the existing fail-safe for fragments that
    # lack enough grammar to classify safely.
    for claim in PROHIBITED_CLAIMS:
        out = re.sub(
            re.escape(claim),
            "may help with your specific workload",
            out,
            flags=re.IGNORECASE,
        )

    replacements = {
        r"\b100%\b": "a high degree of",
        r"\balways faster\b": "often faster in eligible cases",
        r"\balways\b": "often",
        r"\bunlimited\b": "substantial",
    }
    for pattern, repl in replacements.items():
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    # Appendix-B canonical-wording substitutions (always applied).
    for pattern, repl in CANONICAL_SUBSTITUTIONS:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# v6.0 Phase 3: the commercial-reply-to-support-question pattern
# ─────────────────────────────────────────────────────────────────────────────
# §19.5 and Playbook §12D: a support question can NEVER be answered with a commercial
# claim. "A support reply helps with the problem and stops. It does not mention another
# workload, an expansion, a renewal, or a next agreement — NO MATTER HOW NATURAL THE
# SEGUE SEEMS."
#
# Defined HERE so the set stays SINGLE-SOURCED (§11.1): ``stream_guard`` imports from this
# module, so a pattern added here is enforced mid-stream AND at settle. Defining it in the
# guard instead would enforce it while streaming and miss it on a non-streamed reply.
COMMERCIAL_IN_SUPPORT_PATTERNS = [
    r"\bexpan(?:d|sion|ding)\b",
    r"\bupgrade\b",
    r"\brenewal\b",
    r"\bnext agreement\b",
    r"\banother workload\b",
    r"\badditional workload\b",
    r"\bwhile we(?:\'re| are) (?:here|at it)\b",
    r"\bhave you considered\b",
    r"\bwould also benefit\b",
    r"\bcross[- ]?sell\b",
    r"\bupsell\b",
    r"\blicen[cs]e (?:extension|expansion)\b",
    r"\bnew contract\b",
    r"\bextend(?:ing)? (?:your|the) (?:licen[cs]e|agreement|contract|scope)\b",
    r"\bgood (?:time|moment) to (?:discuss|talk about)\b",
]

_COMMERCIAL_IN_SUPPORT_RE = re.compile(
    "|".join(COMMERCIAL_IN_SUPPORT_PATTERNS), re.IGNORECASE
)


def has_commercial_in_support(text: str) -> bool:
    """True when a reply intended for a support thread carries a commercial move."""
    return bool(text and _COMMERCIAL_IN_SUPPORT_RE.search(text))


def find_commercial_in_support(text: str) -> list[str]:
    """The matched commercial phrases, for the cockpit."""
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _COMMERCIAL_IN_SUPPORT_RE.finditer(text)})
