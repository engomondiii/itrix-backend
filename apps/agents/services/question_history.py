"""
Question history and duplicate suppression (Backend v6.0 §5.4).

    checked against the thread's question history to PREVENT REPETITION

── WHY REPETITION IS THE FAILURE THAT MATTERS ───────────────────────────────
The risk register names it alongside non-termination: *the question loop never
terminates, OR ASKS THE SAME THING REPEATEDLY*. They are the same failure from the
visitor's side. Being asked what platform you use for a third time does not read as
thoroughness; it reads as not listening — which is the one thing the surface promises it
is doing.

Similarity is measured on normalised token overlap rather than exact string match,
because "What does the workload run on?" and "What platform does it run on?" are the
same question wearing different words.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("itrix")

# Above this Jaccard overlap, two questions are treated as the same question.
SIMILARITY_THRESHOLD = 0.6

_STOPWORDS = {
    "what", "which", "how", "when", "where", "who", "why", "is", "are", "do", "does",
    "did", "the", "a", "an", "your", "you", "of", "in", "on", "for", "to", "and", "or",
    "it", "that", "this", "would", "could", "can", "we", "us", "our", "any", "some",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of content words. 1.0 = the same question."""
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def asked_for(thread) -> list[str]:
    """Every question already put to this visitor, oldest first."""
    try:
        from apps.journey.models_artifacts import QuestionSuggestion

        return list(
            QuestionSuggestion.objects.filter(thread=thread)
            .order_by("created_at")
            .values_list("primary_text", flat=True)
        )
    except Exception:  # noqa: BLE001
        return []


def count_for(thread) -> int:
    """How many questions have been asked — the input to the budget check."""
    try:
        from apps.journey.models_artifacts import QuestionSuggestion

        return QuestionSuggestion.objects.filter(thread=thread).count()
    except Exception:  # noqa: BLE001
        return 0


def is_duplicate(thread, candidate: str) -> bool:
    """Whether ``candidate`` repeats something already asked."""
    if not (candidate or "").strip():
        return True
    for previous in asked_for(thread):
        if similarity(previous, candidate) >= SIMILARITY_THRESHOLD:
            logger.debug("question suppressed as duplicate: %r ~ %r", candidate, previous)
            return True
    return False


def dimensions_already_targeted(thread) -> set[str]:
    """
    Which dimensions we have already asked about.

    Used to steer the generator toward something NEW even when the previous answer was
    unsatisfying — asking the same dimension again with different words is still asking
    the same thing again.
    """
    try:
        from apps.journey.models_artifacts import QuestionSuggestion

        return set(
            QuestionSuggestion.objects.filter(thread=thread)
            .exclude(target_dimension="")
            .values_list("target_dimension", flat=True)
        )
    except Exception:  # noqa: BLE001
        return set()


def record(thread, *, primary: str, chips: list[str] | None = None,
           target_dimension: str = "", message=None, agent_run_id: str = ""):
    """Persist a question so it is never asked twice."""
    try:
        from apps.journey.models_artifacts import QuestionSuggestion

        return QuestionSuggestion.objects.create(
            thread=thread,
            message=message,
            primary_text=primary[:500],
            chips=chips or [],
            target_dimension=target_dimension,
            agent_run_id=str(agent_run_id or ""),
        )
    except Exception:  # noqa: BLE001
        logger.debug("question not recorded (model unavailable)")
        return None
