"""
The deterministic stop rule (Backend v6.0 §5.3, Architecture §3.1).

    The loop stops on the EARLIEST of:
      1. all dimensions required for the current state are covered
      2. QUESTION_BUDGET_PER_STATE is exhausted (3 in Stage 1, 4 in Stage 2)
      3. the visitor declines, asks for the outcome directly, or asks for a human
      4. a risk or sensitivity signal requires Governance hand-off

    stop_reason is persisted and readable in the cockpit.

── WHY THIS IS THE MOST IMPORTANT FUNCTION IN THE QUESTION LOOP ─────────────
It is the answer to "what stops this thing asking questions forever?". The risk register
names it: *the question loop never terminates, or asks the same thing repeatedly*.

Every one of the four conditions is checkable WITHOUT a model. Condition 3 in particular
— the visitor asking us to stop — must never be a judgement call: when someone says
"just tell me", the correct behaviour is to stop asking, immediately and every time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger("itrix")

STOP_COVERED = "dimensions_covered"
STOP_BUDGET = "question_budget_exhausted"
STOP_VISITOR_DECLINED = "visitor_declined"
STOP_ASKED_FOR_OUTCOME = "visitor_asked_for_outcome"
STOP_ASKED_FOR_HUMAN = "visitor_asked_for_human"
STOP_GOVERNANCE_HANDOFF = "governance_handoff"

# Stage 1 is frictionless; Stage 2 is earned and gets one more question.
STAGE_1_STATES = {1, 2}


def question_budget(journey_state: int) -> int:
    base = int(getattr(settings, "QUESTION_BUDGET_PER_STATE", 3))
    return base if journey_state in STAGE_1_STATES else base + 1


# The visitor telling us to stop. Broad on purpose: a false positive stops asking, which
# is recoverable. A false negative keeps interrogating someone who asked us not to.
_DECLINE = re.compile(
    r"\b(?:no more questions|stop asking|enough questions|i(?:'m| am) done|"
    r"that(?:'s| is) all|no thanks|not interested|skip (?:this|the questions)|"
    r"i(?:'d| would) rather not|prefer not to say)\b",
    re.IGNORECASE,
)
_ASKED_FOR_OUTCOME = re.compile(
    r"\b(?:just (?:tell|show|give) me|what(?:'s| is) the (?:answer|result|outcome|verdict)|"
    r"get to the point|can you just|show me (?:the|your) (?:brief|assessment|result)|"
    r"what do you (?:recommend|suggest)|skip to)\b",
    re.IGNORECASE,
)
_ASKED_FOR_HUMAN = re.compile(
    r"\b(?:speak (?:to|with) (?:a|someone|a real)|talk to (?:a|someone)|"
    r"real person|human being|a human|call me|contact me|sales (?:rep|person)|"
    r"can someone (?:call|email)|put me through)\b",
    re.IGNORECASE,
)

# Sensitivity signals requiring Governance hand-off rather than another question.
_SENSITIVITY = re.compile(
    r"\b(?:classified|itar\b|export control|itar-controlled|state secret|"
    r"under (?:embargo|investigation)|litigation|lawsuit|breach|incident response)\b",
    re.IGNORECASE,
)


@dataclass
class StopDecision:
    """Whether to keep asking, and — if not — WHY. The reason is persisted."""

    should_continue: bool
    reason: str = ""
    detail: str = ""
    questions_asked: int = 0
    budget: int = 0

    @property
    def budget_remaining(self) -> int:
        return max(0, self.budget - self.questions_asked)


def evaluate(*, thread=None, coverage=None, journey_state: int = 2,
             questions_asked: int = 0, last_visitor_text: str = "") -> StopDecision:
    """
    Apply the four conditions in order. The EARLIEST one wins.

    Order matters: the visitor asking for a human outranks an unmet coverage
    requirement, because continuing to qualify someone who asked for a person is the
    rudest possible outcome.
    """
    budget = question_budget(journey_state)

    # Condition 4 first: a sensitivity signal must not be buried under a budget check.
    if last_visitor_text and _SENSITIVITY.search(last_visitor_text):
        return StopDecision(False, STOP_GOVERNANCE_HANDOFF,
                            "sensitivity signal detected", questions_asked, budget)

    # Condition 3: the visitor asked us to stop, in any of its three forms.
    if last_visitor_text:
        if _ASKED_FOR_HUMAN.search(last_visitor_text):
            return StopDecision(False, STOP_ASKED_FOR_HUMAN,
                                "visitor asked for a person", questions_asked, budget)
        if _ASKED_FOR_OUTCOME.search(last_visitor_text):
            return StopDecision(False, STOP_ASKED_FOR_OUTCOME,
                                "visitor asked for the outcome", questions_asked, budget)
        if _DECLINE.search(last_visitor_text):
            return StopDecision(False, STOP_VISITOR_DECLINED,
                                "visitor declined to continue", questions_asked, budget)

    # Condition 1: everything required for this state is covered.
    if coverage is not None and coverage.is_complete_for(journey_state):
        return StopDecision(False, STOP_COVERED,
                            "all required dimensions covered", questions_asked, budget)

    # Condition 2: budget exhausted.
    if questions_asked >= budget:
        return StopDecision(False, STOP_BUDGET,
                            f"asked {questions_asked} of {budget}", questions_asked, budget)

    return StopDecision(True, "", "", questions_asked, budget)


def loop_should_continue(lead) -> bool:
    """
    The boolean ``journey.services.gate.question_loop_open`` delegates to.

    Phase 1 shipped a band check as a placeholder and delegates here once
    ENABLE_ADAPTIVE_QUESTIONS is on — so this is the function that takes over.
    """
    from apps.journey.models import journey_number

    state = journey_number(getattr(lead, "journey_state", None)) or 1
    if state not in (1, 2):
        return False

    thread = _thread_for(lead)
    if thread is None:
        return True

    from apps.agents.services import coverage as coverage_svc
    from apps.agents.services import question_history

    decision = evaluate(
        thread=thread,
        coverage=coverage_svc.build_for_thread(thread),
        journey_state=state,
        questions_asked=question_history.count_for(thread),
        last_visitor_text=_last_visitor_text(thread),
    )
    return decision.should_continue


def _thread_for(lead):
    try:
        from apps.conversations.models import Thread

        return Thread.objects.filter(lead=lead).order_by("-last_activity_at").first()
    except Exception:  # noqa: BLE001
        return None


def _last_visitor_text(thread) -> str:
    from apps.conversations.models import Message

    message = (
        Message.objects.filter(thread=thread, sender_kind__in=["visitor", "client"])
        .order_by("-seq", "-created_at")
        .first()
    )
    return (message.body or "") if message else ""


def persist_stop_reason(review_session, decision: StopDecision) -> None:
    """Record why the loop stopped so the cockpit can audit an unproductive loop."""
    if review_session is None or decision.should_continue:
        return
    try:
        review_session.stop_reason = decision.reason
        review_session.save(update_fields=["stop_reason", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.debug("stop_reason not persisted (field unavailable)")
