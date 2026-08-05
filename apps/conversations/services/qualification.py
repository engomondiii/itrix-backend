"""
Qualification loop orchestration for the live conversational surface.

── WHAT WAS BROKEN ──────────────────────────────────────────────────────────
The conversational surface (``apps/conversations``) never drove the qualification
loop. The coverage tracker, the stop rule and the question generator all existed
and all operate on a thread, but nothing on the turn path called them, and the
loop-closing transition (``LOOP_CLOSED``) had no caller anywhere. So the loop
never advanced and never ended: the same questions were re-asked forever.

This module is the missing wiring. It is deliberately thin — every hard decision
(what "covered" means, when to stop, how to word a question) already lives in
``apps/agents/services`` and is reused unchanged. This module only sequences them
and connects them to state (``thread_state``) and to the socket (``fan_out``).

── THE TWO ENTRY POINTS ─────────────────────────────────────────────────────
``advance_on_turn(thread, body)``   — run AFTER the visitor turn is persisted and
    BEFORE the reply is generated. Moves ARRIVED -> IN_REVIEW on the first turn,
    then evaluates coverage + the stop rule and closes the loop (IN_REVIEW ->
    DIAGNOSED) when the qualification band is satisfied or the visitor asked to
    stop. Deterministic; Layer 1 stays LLM-free.

``suggest_next(thread)``            — run AFTER the reply is delivered. While the
    loop is still open, generates the next question (wording only is model-assisted,
    bound to Claim-Card level 1) and broadcasts ``question.suggested`` so the
    visitor's composer shows the follow-up chips. This is the "predict the next
    prompt" behaviour: the surface always tells the visitor what to say next.

Both are best-effort. A failure here never affects the persisted turn or the reply.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("itrix")


def _adaptive_on() -> bool:
    return bool(getattr(settings, "ENABLE_ADAPTIVE_QUESTIONS", False))


def advance_on_turn(thread, body: str) -> None:
    """
    Advance the qualification state for a freshly persisted visitor turn.

    Ordering matters: the first turn opens the loop (1 -> 2); every turn then updates
    coverage and asks the stop rule whether the band is now satisfied. When it is, the
    loop closes (2 -> 3) and the reflection hand-off fires. All of this is deterministic.
    """
    if thread is None:
        return

    from apps.conversations.services import thread_state

    # 1) First turn on an empty thread opens the review. Idempotent for later turns.
    try:
        thread_state.enter_in_review(thread)
    except Exception:  # noqa: BLE001
        logger.debug("enter_in_review failed for thread %s", getattr(thread, "id", "?"))

    if not _adaptive_on():
        # Without the adaptive loop the deterministic band still governs state via
        # enter_in_review above; there is no coverage-driven close to evaluate — but
        # the client-page reveal below still runs (it has its own gates).
        _maybe_reveal(thread, body)
        return

    state_number = thread_state.current_state_number(thread)
    # The qualification band is states 1-2. We only evaluate the stop rule / loop close
    # while inside it; past it we fall through to the reveal check.
    if state_number in (1, 2):
        _evaluate_and_close_loop(thread, state_number, body)

    # 2) CLIENT-PAGE REVEAL (3 -> 4). Runs on EVERY turn, with its own gates: it acts
    # once the loop has closed (DIAGNOSED) AND an email has been given anywhere in the
    # conversation. This is what carries the visitor past DIAGNOSED to the custom page.
    _maybe_reveal(thread, body)

    # 3) THE CONTACT ASK. The reveal above needs an email address, and until this
    # existed nothing ever asked for one — so a conversation that closed its loop
    # sat at DIAGNOSED forever while the model, given no instruction, promised a
    # human follow-up instead. Deterministic, budgeted, and a no-op once an address
    # has been given. Runs AFTER the reveal so a turn that just revealed the page
    # never also asks for the address it just used.
    _maybe_ask_for_contact(thread, body)


def _evaluate_and_close_loop(thread, state_number: int, body: str) -> None:
    """The stop-rule evaluation + loop close, factored out of advance_on_turn."""
    from apps.conversations.services import thread_state

    try:
        from apps.agents.services import coverage as coverage_svc
        from apps.agents.services import stop_rule

        coverage = coverage_svc.snapshot(thread)  # computes AND persists per-dimension
        decision = stop_rule.evaluate(
            thread=thread,
            coverage=coverage,
            journey_state=state_number,
            questions_asked=_questions_asked(thread),
            last_visitor_text=body or "",
        )
    except Exception:  # noqa: BLE001
        logger.debug("stop-rule evaluation failed for thread %s", getattr(thread, "id", "?"))
        return

    # ``should_continue`` False means the loop should END for one of the four reasons
    # (covered / budget / visitor asked to stop / sensitivity). Close it once.
    if not decision.should_continue:
        try:
            closed = thread_state.close_qualification_loop(thread, reason=decision.reason)
            if closed:
                logger.info(
                    "qualification loop closed for thread %s (%s)",
                    getattr(thread, "id", "?"), decision.reason,
                )
        except Exception:  # noqa: BLE001
            logger.debug("loop close failed for thread %s", getattr(thread, "id", "?"))


def _maybe_reveal(thread, body: str) -> None:
    """
    Attempt the client-page reveal; stash the outcome for the reply to surface.

    Runs on every turn. The bridge itself gates on DIAGNOSED + an email given
    anywhere in the conversation, so this is a cheap no-op until the visitor is
    actually ready.
    """
    try:
        from apps.conversations.services import reveal_bridge

        outcome = reveal_bridge.maybe_reveal_client_page(thread, body or "")
        if outcome.get("revealed"):
            # Stash on the instance so the generation path can (a) tell the AI the page
            # is ready so it presents it in its own voice, and (b) append the link as a
            # transport-independent fallback.
            setattr(thread, "_client_page_reveal", outcome)
    except Exception:  # noqa: BLE001 - reveal is best-effort; never break the turn
        logger.debug("client-page reveal check failed for thread %s", getattr(thread, "id", "?"))


def _maybe_ask_for_contact(thread, body: str) -> None:
    """
    Decide whether this turn's reply should ask for an email address, and stash it.

    Stashed on the instance exactly as ``_client_page_reveal`` is, so the generation
    path picks it up through ``conversation_context.build_turn_extra`` on both the
    HTTP and the WebSocket transports without either of them learning a new rule.

    ── THE STASH IS ALWAYS OVERWRITTEN, NEVER JUST SET ──────────────────────
    The WebSocket consumer holds ONE Thread instance for the life of the socket, so
    every turn in that session sees the same Python object. A decision written on
    turn N and merely left in place would still be there on turn N+1 — including on
    the turn that reveals the page, where the reply would hand over the personalised
    page and then ask for the address it had just used. So the attribute is assigned
    on every turn, whatever the decision, and a no-ask decision clears it.
    """
    decision = None
    try:
        from apps.conversations.services import contact_ask

        evaluated = contact_ask.evaluate(thread, body or "")
        if evaluated.get("ask"):
            decision = evaluated
    except Exception:  # noqa: BLE001 - the ask is best-effort; never break the turn
        logger.debug("contact-ask evaluation failed for thread %s", getattr(thread, "id", "?"))
    setattr(thread, "_contact_ask", decision)


def suggest_next(thread, *, message=None) -> dict:
    """
    Generate and broadcast the next question, IF the loop is still open.

    Returns the ``question.suggested`` payload that was broadcast (``{}`` when nothing
    was suggested — loop closed, adaptive questions off, or no dimension left). Runs
    after the reply so the follow-up chips appear beneath the answer, never instead of
    it.
    """
    if thread is None or not _adaptive_on():
        return {}

    from apps.conversations.services import thread_state

    state_number = thread_state.current_state_number(thread)
    if state_number not in (1, 2):
        # Loop is closed (or past the band): no more questions, by design.
        return {}

    try:
        from apps.agents.services import coverage as coverage_svc
        from apps.agents.services import question_generator
        from apps.conversations.services import conversation_context

        coverage = coverage_svc.build_for_thread(thread)
        question = question_generator.generate(
            thread=thread,
            coverage=coverage,
            journey_state=state_number,
            recent_turns=conversation_context.recent_turns(thread),
        )
        payload = question_generator.emit(thread, question, message=message)
    except Exception:  # noqa: BLE001
        logger.debug("next-question generation failed for thread %s", getattr(thread, "id", "?"))
        return {}

    if not payload:
        return {}

    # Denormalise the running question count onto the thread for the budget check.
    _bump_questions_asked(thread)

    # Broadcast so the composer shows the follow-up chips (frontend: useSuggestions
    # listens for ``question.suggested`` with {threadId, chips}).
    try:
        from apps.conversations.services.fan_out import broadcast_question_suggested

        broadcast_question_suggested(thread.group_name, payload)
    except Exception:  # noqa: BLE001
        logger.debug("question.suggested fan-out failed for thread %s", getattr(thread, "id", "?"))

    return payload


def _questions_asked(thread) -> int:
    """
    How many questions have been asked in this thread's band.

    Prefers the denormalised counter on the thread; falls back to the authoritative
    QuestionSuggestion count via question_history if the counter is unset.
    """
    n = int(getattr(thread, "questions_asked", 0) or 0)
    if n:
        return n
    try:
        from apps.agents.services import question_history

        return int(question_history.count_for(thread))
    except Exception:  # noqa: BLE001
        return 0


def _bump_questions_asked(thread) -> None:
    try:
        thread.questions_asked = int(getattr(thread, "questions_asked", 0) or 0) + 1
        thread.save(update_fields=["questions_asked", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.debug("could not bump questions_asked on thread %s", getattr(thread, "id", "?"))
