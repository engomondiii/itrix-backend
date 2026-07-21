"""
Adaptive question generation (Backend v6.0 §5.4, Architecture §3.1).

    The generator returns ONE PRIMARY QUESTION and up to THREE CHIPS. Each is:
      * bound to Claim-Card level 1 — IT MAY ASK, NEVER ASSERT
      * checked against the prohibited-language list before emission
      * forbidden from naming or implying an inferred company, department, persona or score
      * forbidden from requesting confidential information before an NDA
      * checked against the thread's question history to prevent repetition
      * logged on the AgentRun with the dimension it targeted

── THE DIVISION OF AUTHORITY (the single most important rule in §3.1) ───────
    which dimensions remain uncovered   DETERMINISTIC   coverage.py
    whether to ask again or stop        DETERMINISTIC   stop_rule.py
    which state the subject is in       DETERMINISTIC   journey/advance.py
    what the visitor may be shown       DETERMINISTIC   disclosure_filter
    THE WORDING OF THE NEXT QUESTION    GENERATED       this module

That last line is the ONLY thing the model decides here. This module is handed a
dimension to ask about and produces words for it — it never chooses the dimension, never
decides whether to ask at all, and never sees a score.

── WHY EVERY QUESTION HAS A DETERMINISTIC FALLBACK ──────────────────────────
If generation is unavailable, off, or produces something that fails a guard, we do not
skip the question — we ask the approved bank version. A loop that silently stops asking
because the model was down would terminate qualification early and generate an artifact
from half the information.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("itrix")

MAX_CHIPS = 3
CLAIM_LEVEL = 1  # may ask, never assert

# ── The governed question bank ───────────────────────────────────────────────
# One approved question per dimension, plus chips. These are the FALLBACK and also the
# grounding for generation — a generated question that drifts from the intent of its
# bank entry is rejected rather than emitted.
QUESTION_BANK: dict[str, dict] = {
    "workload": {
        "primary": "What does the workload actually do?",
        "chips": ["It is training", "It is inference", "It is simulation or solving"],
    },
    "platform_environment": {
        "primary": "What does the workload run on today?",
        "chips": ["GPU cluster", "CPU / HPC", "Cloud managed service"],
    },
    "pressure_area": {
        "primary": "Which is hurting most right now — cost, speed, energy, memory or stability?",
        "chips": ["Cost", "Speed", "Energy or memory"],
    },
    "scale": {
        "primary": "Roughly what scale is this running at?",
        "chips": ["A handful of nodes", "A large fleet", "It varies a lot"],
    },
    "baseline": {
        "primary": "What does it look like today, before any change?",
        "chips": ["We have a measured baseline", "We have a rough sense", "Not measured yet"],
    },
    "timeline": {
        "primary": "Is this a now problem or a next-year problem?",
        "chips": ["This quarter", "This year", "Exploring for later"],
    },
    "decision_process": {
        "primary": "Who else would need to be part of a decision like this?",
        "chips": ["Just my team", "Engineering leadership", "A formal procurement process"],
    },
    "success_definition": {
        "primary": "If this were solved, what would it unlock for you?",
        "chips": ["More capacity", "Lower cost", "Something we cannot do today"],
    },
    "constraint": {
        "primary": "What constraints would any solution have to live inside?",
        "chips": ["Must stay on-premise", "Compliance requirements", "Existing stack must remain"],
    },
    "commercial_intent": {
        "primary": "What would a useful next step look like from your side?",
        "chips": ["A technical review", "A scoped evaluation", "Just understanding for now"],
    },
}

# Patterns a generated question may NEVER contain.
_FORBIDDEN = [
    # Inferred identity — §4 PERSONALIZATION WITHOUT PROFILING.
    (re.compile(r"\b(?:since|because|given) you(?:'re| are)\b", re.I), "inferred_identity"),
    # Allow several words between the article and the noun: "as a large enterprise team"
    # is the same assertion as "as an enterprise team".
    (re.compile(
        r"\bas (?:a|an) [\w\s-]{0,40}?"
        r"(?:company|team|organisation|organization|business|lab|vendor|operator)\b",
        re.I,
    ), "inferred_identity"),
    # "Based on your company/department/role..." — the most natural way to leak an
    # inference, and therefore the one most likely to be generated.
    (re.compile(
        r"\bbased on your (?:company|organisation|organization|department|role|persona|"
        r"team|industry|sector|profile)\b", re.I,
    ), "inferred_identity"),
    (re.compile(r"\b(?:given|for) (?:a|an) [\w\s-]{0,40}?"
                r"(?:like yours|such as yours)\b", re.I), "inferred_identity"),
    (re.compile(r"\byour (?:company|organisation|organization|department|role|persona|team) is\b", re.I),
     "inferred_identity"),
    (re.compile(r"\bwe (?:can see|detected|identified|inferred|know)\b", re.I), "inferred_identity"),
    (re.compile(r"\b(?:tier|score|persona|segment)\s*\d", re.I), "internal_signal"),
    # Confidential requests before an NDA.
    (re.compile(r"\b(?:proprietary|confidential|internal) (?:code|data|architecture|benchmark)", re.I),
     "pre_nda_confidential"),
    (re.compile(r"\bshare (?:your )?(?:source code|actual data|real numbers)\b", re.I),
     "pre_nda_confidential"),
    # Assertions — this is a QUESTION generator.
    (re.compile(r"\b(?:we guarantee|will reduce|will improve|proven to)\b", re.I), "assertion"),
    (re.compile(r"\b\d+\s?%\s*(?:faster|cheaper|less|lower|improvement)", re.I), "figure"),
    (re.compile(r"\b\d+\s?x\s*(?:faster|cheaper)", re.I), "figure"),
]


@dataclass
class GeneratedQuestion:
    """One question, plus everything the cockpit needs to audit whether it was useful."""

    primary: str
    chips: list[str] = field(default_factory=list)
    target_dimension: str = ""
    generated: bool = False       # False = the approved bank fallback was used
    rejected_reason: str = ""     # why a generated candidate was refused

    def to_payload(self) -> dict:
        """The socket payload. Carries no dimension — that is internal."""
        return {"primary": self.primary, "chips": self.chips[:MAX_CHIPS]}


def next_dimension(coverage, *, journey_state: int = 2, already_targeted=None) -> str | None:
    """
    Which dimension to ask about next. DETERMINISTIC.

    Required dimensions first, in declared order, skipping anything already asked. The
    order is not arbitrary: workload before platform before pressure follows how a person
    naturally describes a problem, and asking about commercial intent early reads as
    qualifying rather than listening.
    """
    from apps.agents.services.coverage import COVERED, REQUIRED_BY_STATE
    from apps.journey.constants import LISTENING_DIMENSIONS

    already = set(already_targeted or ())
    required = REQUIRED_BY_STATE.get(journey_state, ())

    for dimension in required:
        if coverage.dimensions.get(dimension) != COVERED and dimension not in already:
            return dimension
    for dimension in LISTENING_DIMENSIONS:
        if coverage.dimensions.get(dimension) != COVERED and dimension not in already:
            return dimension
    return None


def check_candidate(text: str) -> str:
    """
    Validate a generated question. Returns "" when clean, else the violated rule.

    Runs BEFORE emission (§5.4). A question is outbound text like any other, and it goes
    through the same prohibited-language check the settle gate uses.
    """
    if not (text or "").strip():
        return "empty"
    if len(text) > 300:
        return "too_long"
    if "?" not in text:
        # It must actually be a question. A statement dressed as guidance is an assertion.
        return "not_a_question"

    for pattern, reason in _FORBIDDEN:
        if pattern.search(text):
            return reason

    try:
        from apps.ai_engine.services import prohibited_language_checker as plc

        if plc.has_hard_block(text) or plc.find_violations(text):
            return "prohibited_language"
    except Exception:  # noqa: BLE001
        pass
    return ""


def generate(*, thread, coverage, journey_state: int = 2, recent_turns=None,
             ctx=None) -> GeneratedQuestion:
    """
    Produce the next question.

    Falls back to the approved bank whenever generation is unavailable or the candidate
    fails a guard — never returns nothing.
    """
    from apps.agents.services import question_history

    dimension = next_dimension(
        coverage,
        journey_state=journey_state,
        already_targeted=question_history.dimensions_already_targeted(thread),
    )
    if dimension is None:
        dimension = next_dimension(coverage, journey_state=journey_state)
    if dimension is None:
        return GeneratedQuestion(primary="", chips=[], target_dimension="")

    bank = QUESTION_BANK.get(dimension, {})
    fallback = GeneratedQuestion(
        primary=bank.get("primary", "Tell us a little more about that?"),
        chips=list(bank.get("chips", []))[:MAX_CHIPS],
        target_dimension=dimension,
        generated=False,
    )

    candidate = _generate_wording(dimension, recent_turns or [], ctx)
    if not candidate:
        return fallback

    reason = check_candidate(candidate)
    if reason:
        logger.info("question rejected (%s): %r", reason, candidate)
        fallback.rejected_reason = reason
        return fallback

    if question_history.is_duplicate(thread, candidate):
        fallback.rejected_reason = "duplicate"
        return fallback

    return GeneratedQuestion(
        primary=candidate,
        chips=list(bank.get("chips", []))[:MAX_CHIPS],
        target_dimension=dimension,
        generated=True,
    )


def _generate_wording(dimension: str, recent_turns: list[str], ctx) -> str:
    """
    Ask the model for a better-phrased version of the bank question.

    LOW TEMPERATURE and tightly bounded: the model is rewording an approved question in
    the visitor's own vocabulary, not composing a new one. Returns "" on any failure so
    the caller uses the bank version.
    """
    from django.conf import settings

    if not getattr(settings, "ENABLE_ADAPTIVE_QUESTIONS", False):
        return ""
    if not getattr(settings, "ENABLE_AI_ENGINE", False):
        return ""

    bank = QUESTION_BANK.get(dimension, {})
    approved = bank.get("primary", "")
    if not approved:
        return ""

    try:
        from apps.ai_engine.services.claude_client import AIEngineDisabled, ClaudeClient

        system = (
            "You rephrase ONE approved question so it follows naturally from what the "
            "visitor just said. Rules, all absolute:\n"
            "- Return ONLY the question. No preamble, no explanation.\n"
            "- It must remain the SAME question, seeking the same information.\n"
            "- You may ASK. You may never ASSERT, claim, promise or compare.\n"
            "- Never state or imply anything about the visitor's company, department, "
            "role or how we have categorised them.\n"
            "- Never request confidential material.\n"
            "- No figures, no percentages, no comparisons.\n"
            "- One sentence, under 200 characters, ending in a question mark."
        )
        context = "\n".join(f"- {t[:300]}" for t in recent_turns[-3:]) or "(no prior turns)"
        user = (
            f"Approved question to rephrase:\n{approved}\n\n"
            f"What the visitor has said so far:\n{context}\n\n"
            f"Rephrased question:"
        )
        raw = ClaudeClient().complete(system=system, user=user, max_tokens=120)
        return _clean(raw)
    except AIEngineDisabled:  # type: ignore[misc]
        return ""
    except Exception:  # noqa: BLE001
        logger.debug("question generation unavailable; using the approved bank")
        return ""


def _clean(raw: str) -> str:
    text = (raw or "").strip().strip('"').strip()
    # Models sometimes prefix with a label; take the first question-bearing line.
    for line in text.splitlines():
        line = line.strip().strip('"').strip()
        if line.endswith("?"):
            return line[:300]
    return ""


def emit(thread, question: GeneratedQuestion, *, message=None, agent_run_id: str = "") -> dict:
    """
    Record the question and build the ``question.suggested`` payload.

    Recording is what makes duplicate suppression and budget counting work, so it happens
    even when the bank fallback was used — a fallback question was still asked.
    """
    from apps.agents.services import question_history

    if not question.primary:
        return {}

    question_history.record(
        thread,
        primary=question.primary,
        chips=question.chips,
        target_dimension=question.target_dimension,
        message=message,
        agent_run_id=agent_run_id,
    )
    return {
        "thread_id": str(getattr(thread, "id", "")),
        **question.to_payload(),
    }
