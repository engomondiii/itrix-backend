"""
Streaming governance, Part 2 — the stream guard (Backend v6.0 §6.2).

DURING generation, a DETERMINISTIC matcher runs over the emerging token stream looking
for prohibited patterns:

    benchmark figures · guarantee language · pricing · exclusivity terms ·
    competitor claims · mechanism disclosure · "lookup-table" phrasing ·
    inferred-identity assertions

On a match the stream HALTS IMMEDIATELY, the partial text is DISCARDED from the client
via ``message.halted``, and the turn is re-routed to the approval queue.

── THIS IS A HARD STOP, NOT A WARNING ───────────────────────────────────────
There is no "flag and continue" mode. A prohibited claim that has already been rendered
has already been read; retracting it afterwards is damage control, not governance.

── THE SINGLE-SOURCE RULE ───────────────────────────────────────────────────
The pattern set is SINGLE-SOURCED with ``apps.ai_engine.services.prohibited_language_checker``
so a pattern cannot be enforced at settle but missed mid-stream (Backend v6.0 §11.1).
This module imports those patterns rather than restating them. If you add a pattern,
add it THERE and both paths pick it up.

── WHY MATCH ON A SLIDING WINDOW ────────────────────────────────────────────
Tokens arrive in fragments: "3", "0", "%", " faster" is four tokens and one violation.
Matching per-token would never see it. The guard therefore accumulates and matches over
a trailing window, so a pattern split across token boundaries is still caught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("itrix")

# How much trailing text to keep for cross-token matching. Comfortably longer than the
# longest pattern so a phrase split across many small tokens is still matched whole.
WINDOW_CHARS = 400


@dataclass
class GuardHit:
    """One prohibited-pattern match, recorded for the cockpit."""

    pattern: str
    matched_text: str
    position: int
    category: str = "prohibited"


@dataclass
class GuardState:
    """Mutable state for one streamed turn."""

    accumulated: str = ""
    halted: bool = False
    hits: list[GuardHit] = field(default_factory=list)
    discarded_chars: int = 0

    @property
    def first_hit(self) -> GuardHit | None:
        return self.hits[0] if self.hits else None


def _compiled_patterns() -> list[tuple[str, re.Pattern, str]]:
    """
    Build the matcher set, SINGLE-SOURCED from the prohibited-language checker.

    Returns ``(name, compiled, category)`` triples. Import failure is fatal for
    streaming: without the shared set we cannot guarantee the two paths agree, and the
    conservative response is to refuse to stream rather than to stream unguarded.
    """
    from apps.ai_engine.services import prohibited_language_checker as plc

    patterns: list[tuple[str, re.Pattern, str]] = []

    # 1) Hard-block patterns — unapproved benchmark figures, quantified comparisons.
    for raw in plc.HARD_BLOCK_PATTERNS:
        patterns.append((raw, re.compile(raw, re.IGNORECASE), "benchmark"))

    # 2) Exact prohibited claims from the brand's claims discipline.
    for claim in plc.PROHIBITED_CLAIMS:
        patterns.append((claim, re.compile(re.escape(claim), re.IGNORECASE), "prohibited_claim"))

    # 3) Canonical-wording violations. The most important: ALPHA Core is ALWAYS
    #    "table-free index-ordered algebraic execution" and must NEVER be described as
    #    "lookup-table execution" (Architecture v2.6 §19.5).
    for raw, _replacement in plc.CANONICAL_SUBSTITUTIONS:
        patterns.append((raw, re.compile(raw, re.IGNORECASE), "canonical_wording"))

    # 4) Stream-specific patterns: things that must never be EMITTED to a visitor even
    #    though they may legitimately appear in internal text.
    patterns.extend(_STREAM_ONLY_PATTERNS)
    return patterns


# Patterns that only matter on an outbound stream. Kept here (not in the shared checker)
# because they describe DELIVERY, not claim validity — but they are still compiled into
# the same single set so the two paths cannot diverge in practice.
_STREAM_ONLY_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # Pricing must never be emitted by an agent on any public surface.
    (
        r"pricing",
        # NOTE: no leading \b before the currency symbol. "$" is not a word character,
        # so \b would require a word char immediately before it — which never happens
        # after a space. That mistake silently disabled the whole pricing rule.
        re.compile(
            r"(?:\$|USD\s?|KRW\s?|EUR\s?)[\d,]+(?:\.\d+)?(?:\s?(?:k|m|bn|million|billion))?",
            re.IGNORECASE,
        ),
        "pricing",
    ),
    (
        r"percent_of_value",
        re.compile(r"\b\d{1,3}\s?%\s+of\s+(?:the\s+)?value\b", re.IGNORECASE),
        "pricing",
    ),
    # Exclusivity terms are never public and never emitted by an agent.
    (
        r"exclusivity",
        re.compile(
            r"\b(?:exclusive (?:licen[cs]e|rights|deal|terms)|exclusivity (?:premium|fee|period))\b",
            re.IGNORECASE,
        ),
        "exclusivity",
    ),
    # Named-competitor comparison without approval.
    (
        r"competitor_comparison",
        re.compile(
            r"\b(?:better|faster|cheaper|superior|outperforms?)\s+than\s+"
            r"(?:NVIDIA|AMD|Intel|CUDA|cuBLAS|TurboQuant|Google|Microsoft|Amazon|Meta)\b",
            re.IGNORECASE,
        ),
        "competitor",
    ),
    # Mechanism disclosure — the implementation path is trade secret at every tier.
    (
        r"mechanism_disclosure",
        re.compile(
            r"\b(?:the (?:embedding|quantisation|quantization|transfer) (?:map|rule|formula) is"
            r"|implemented by (?:the )?following steps"
            r"|source code (?:for|of) (?:AXIOM|CRE|FQNM))\b",
            re.IGNORECASE,
        ),
        "mechanism",
    ),
    # Inferred-identity assertion. Personalization NEVER means telling the visitor what
    # we think we know about them (§4 PERSONALIZATION WITHOUT PROFILING).
    (
        r"inferred_identity",
        re.compile(
            r"\b(?:we (?:can see|detected|identified|infer(?:red)?) (?:that )?you(?:'re| are)?\b"
            r"|based on your (?:company|organi[sz]ation|department|role|persona)\b"
            r"|since you(?:'re| are) (?:at|with|from) (?:a|an|the)\b)",
            re.IGNORECASE,
        ),
        "inferred_identity",
    ),
    # Guarantee language directed at outcomes.
    (
        r"guarantee_outcome",
        re.compile(
            r"\b(?:we|itri[xX]|alpha)\s+(?:guarantee|guarantees|will guarantee)\b", re.IGNORECASE
        ),
        "guarantee",
    ),
]


def new_state() -> GuardState:
    """Start guarding a fresh streamed turn."""
    return GuardState()


def enabled() -> bool:
    return bool(getattr(settings, "STREAM_GUARD_ENABLED", True))


def inspect(state: GuardState, token: str) -> GuardHit | None:
    """
    Feed one token to the guard.

    Returns a ``GuardHit`` when the emerging text matches a prohibited pattern — at
    which point the CALLER MUST halt the stream immediately and discard the partial
    text. Returns ``None`` when it is safe to forward the token.

    Matching runs over a trailing window so a pattern split across token boundaries is
    still caught.
    """
    if state.halted:
        return state.first_hit
    if not enabled():
        state.accumulated += token or ""
        return None

    previous_len = len(state.accumulated)
    state.accumulated += token or ""

    # Match over a window that includes enough preceding text to span a split pattern.
    window_start = max(0, previous_len - WINDOW_CHARS)
    window = state.accumulated[window_start:]

    for name, compiled, category in _patterns():
        match = compiled.search(window)
        if match:
            hit = GuardHit(
                pattern=name,
                matched_text=match.group(0)[:120],
                position=window_start + match.start(),
                category=category,
            )
            state.halted = True
            state.hits.append(hit)
            state.discarded_chars = len(state.accumulated)
            logger.warning(
                "stream_guard HALT pattern=%s category=%s matched=%r",
                name,
                category,
                hit.matched_text,
            )
            return hit
    return None


_PATTERN_CACHE: list[tuple[str, re.Pattern, str]] | None = None


def _patterns() -> list[tuple[str, re.Pattern, str]]:
    """Compile once per process. Recompiling per token would dominate stream latency."""
    global _PATTERN_CACHE
    if _PATTERN_CACHE is None:
        _PATTERN_CACHE = _compiled_patterns()
    return _PATTERN_CACHE


def reset_pattern_cache() -> None:
    """Drop the compiled cache (tests that monkeypatch the shared pattern set)."""
    global _PATTERN_CACHE
    _PATTERN_CACHE = None


def scan(text: str) -> list[GuardHit]:
    """
    Run the guard over a COMPLETE piece of text.

    Used by the settle stage and by tests. Returns every hit rather than stopping at the
    first, because at settle time the cockpit wants the full picture.
    """
    hits: list[GuardHit] = []
    if not text or not enabled():
        return hits
    for name, compiled, category in _patterns():
        for match in compiled.finditer(text):
            hits.append(
                GuardHit(
                    pattern=name,
                    matched_text=match.group(0)[:120],
                    position=match.start(),
                    category=category,
                )
            )
    return hits


def halt_payload(state: GuardState, *, thread_id: str, message_id: str) -> dict:
    """
    Build the ``message.halted`` payload.

    Carries NO partial text and NO explanation of what matched — the visitor sees only
    the approved halted wording. The matched pattern goes to the cockpit, never to the
    client (§10.5: ``stream_guard_hits`` is a serializer-enforced internal field).
    """
    from apps.governance.services.stream_envelope import HALTED_WORDING

    return {
        "thread_id": str(thread_id),
        "message_id": str(message_id),
        "reason": "governance_halt",
        "replacement_body": HALTED_WORDING,
    }


def record_hits(
    state: GuardState,
    *,
    message_id: str = "",
    thread_id: str = "",
    agent_key: str = "",
    plane: str = "",
) -> None:
    """
    Persist guard hits for cockpit reporting.

    A rising guard-hit rate is treated as RETRIEVAL OR PROMPT DRIFT, not as noise
    (§6.4). Best-effort: a reporting failure must never affect delivery.
    """
    if not state.hits:
        return
    try:
        from apps.governance.models import StreamGuardHit

        for hit in state.hits:
            StreamGuardHit.objects.create(
                kind=StreamGuardHit.Kind.HALT,
                thread_id=str(thread_id or ""),
                message_id=str(message_id or ""),
                agent_key=agent_key or "",
                plane=plane or "",
                pattern=hit.pattern,
                category=hit.category,
                matched_text=hit.matched_text,
                position=hit.position,
                discarded_chars=state.discarded_chars,
            )
    except Exception:  # noqa: BLE001
        logger.exception("stream_guard hit could not be persisted")
