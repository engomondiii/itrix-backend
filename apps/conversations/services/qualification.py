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

    from apps.conversations.services import engagement_state, thread_state

    # Purpose recognition and relationship state are evaluated before the numbered
    # qualification ladder. A Visitor / Technical Evaluator is allowed to stay in the
    # public exploration lane indefinitely; seniority, company, message depth and turn
    # count never open the customer qualification band.
    engagement_decision = None
    try:
        engagement_decision = engagement_state.update_from_turn(thread, body or "")
    except Exception:  # noqa: BLE001
        logger.exception("engagement-state update failed for thread %s", getattr(thread, "id", "?"))

    # Turn-local deterministic copy. Both HTTP and WebSocket transports read this same
    # Thread instance, so the v2.2 stated-mode-change requirement cannot disappear when
    # the model is unavailable. Always overwrite to avoid repeating a stale offer.
    setattr(
        thread,
        "_mode_change_offer",
        engagement_state.mode_change_offer_text(thread)
        if engagement_decision is not None and engagement_decision.mode_change_offered
        else "",
    )

    if not engagement_state.is_customer(thread):
        # Always clear turn-local commercial orchestration. Realtime consumers keep one
        # Thread instance alive for the socket lifetime, so stale attributes would
        # otherwise leak an earlier CTA into a later Visitor answer.
        setattr(thread, "_client_page_reveal", None)
        setattr(thread, "_contact_ask", None)
        return

    # Only an explicit Customer/Strategic Customer relationship enters review.
    try:
        thread_state.enter_in_review(thread)
    except Exception:  # noqa: BLE001
        logger.debug("enter_in_review failed for thread %s", getattr(thread, "id", "?"))

    # ── THE FLAG GATES GENERATION, NOT THE BAND ──────────────────────────────
    # ENABLE_ADAPTIVE_QUESTIONS used to make this function return here, skipping the
    # stop-rule evaluation AND the contact ask. That turned a UI feature flag into a
    # journey switch: with the flag off, nothing could ever close the loop, so the
    # thread sat at IN_REVIEW forever, the contact ask (gated on DIAGNOSED) was
    # unreachable, and the client-page reveal was permanently "not_diagnosed" — even
    # when the visitor volunteered an email address. The conversation dead-ended
    # while the model, given no instruction, improvised a human hand-off.
    #
    # Coverage and the stop rule are deterministic, model-free, and belong to the
    # band itself (Architecture: Layer 1 owns coverage and the stop rule). The flag
    # keeps exactly the scope its name claims — ADAPTIVE QUESTION generation — which
    # ``suggest_next`` below still checks. State advancement is not a feature.
    state_number = thread_state.current_state_number(thread)
    # The qualification band is states 1-2. We only evaluate the stop rule / loop close
    # while inside it; past it we fall through to the reveal check.
    if state_number in (1, 2):
        _evaluate_and_close_loop(
            thread,
            state_number,
            body,
            ignore_proceed_signal=bool(engagement_decision and engagement_decision.mode_change_accepted),
        )

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


def _evaluate_and_close_loop(
    thread, state_number: int, body: str, *, ignore_proceed_signal: bool = False
) -> None:
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
            ignore_proceed_signal=ignore_proceed_signal,
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

    ── THE STASH IS ALWAYS OVERWRITTEN, NEVER JUST SET ──────────────────────
    Same rule as ``_maybe_ask_for_contact`` below, for the same reason: the
    WebSocket consumer holds ONE Thread instance for the life of the socket. A
    reveal stashed on the turn that fired it and merely left in place would still
    be there on every LATER turn in that session — so the reveal directive and the
    appended link would repeat under every subsequent reply. Assign on every turn;
    a no-reveal turn clears it.
    """
    outcome = None
    try:
        from apps.conversations.services import reveal_bridge

        result = reveal_bridge.maybe_reveal_client_page(thread, body or "")
        if result.get("revealed"):
            # Stash on the instance so the generation path can (a) tell the AI the page
            # is ready so it presents it in its own voice, and (b) append the link as a
            # transport-independent fallback.
            outcome = result
    except Exception:  # noqa: BLE001 - reveal is best-effort; never break the turn
        logger.debug("client-page reveal check failed for thread %s", getattr(thread, "id", "?"))
    setattr(thread, "_client_page_reveal", outcome)


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

    from apps.conversations.services import engagement_state, thread_state
    if not engagement_state.is_customer(thread):
        return {}

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
    if not n:
        try:
            from apps.agents.services import question_history

            n = int(question_history.count_for(thread))
        except Exception:  # noqa: BLE001
            n = 0

    # ── THE DELIVERED-REPLY FLOOR ────────────────────────────────────────────
    # Both counters above move only when the QUESTION GENERATOR emits. But the
    # concierge asks a question with essentially every in-band reply of its own —
    # the approved behaviour — whether or not the generator emitted chips for it.
    # When emission stalls (generation off, wording rejected, nothing left in the
    # bank) the counters freeze below the budget and the band can never close on
    # exhaustion: the exact "asks forever" failure the stop rule exists to prevent,
    # reached through its own bookkeeping. Every delivered agent reply in the band
    # was an opportunity to ask, so it is counted as one. Team, system and support
    # messages are not questions and are excluded.
    try:
        from apps.conversations.models import Message, SenderKind

        delivered = Message.objects.filter(
            thread=thread, sender_kind=SenderKind.AGENT
        ).count()
        n = max(n, int(delivered))
    except Exception:  # noqa: BLE001 - a counting failure must never break a turn
        pass
    return n


def _bump_questions_asked(thread) -> None:
    try:
        thread.questions_asked = int(getattr(thread, "questions_asked", 0) or 0) + 1
        thread.save(update_fields=["questions_asked", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.debug("could not bump questions_asked on thread %s", getattr(thread, "id", "?"))
