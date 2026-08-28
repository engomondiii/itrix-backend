"""
The contact ask — the missing stage between DIAGNOSED (3) and CLIENT_PAGE (4).

── WHAT WAS BROKEN ──────────────────────────────────────────────────────────
``reveal_bridge.maybe_reveal_client_page`` gates the personalised page on two
things: the qualification loop having closed (DIAGNOSED), and AN EMAIL ADDRESS
having appeared somewhere in the conversation. Gate 1 is reached deterministically
by the coverage tracker and the stop rule. Gate 2 could only ever be satisfied by
the visitor volunteering an address unprompted — because NOTHING ASKED FOR IT:

  * ``question_generator.QUESTION_BANK`` covers the ten LISTENING_DIMENSIONS, all
    of which are qualification facts. There is no contact dimension, so the
    question loop could never produce the ask.
  * ``qualification.suggest_next`` returns ``{}`` the moment the state leaves the
    (1, 2) band — so at DIAGNOSED, which is exactly where the address is needed,
    the surface stops suggesting anything at all.
  * ``concierge._reveal_directive`` — the only place the model is ever told about
    the personalised page — returns ``""`` unless the page has ALREADY been
    revealed, which requires the email, which requires the ask. Circular.

With no instruction the model did the only sensible generic thing and promised a
human follow-up ("the itriX Assessment Team will be in touch"), which is the exact
ending ``_reveal_directive`` was written to prevent — it was simply on the wrong
side of the gate. The conversation dead-ended at DIAGNOSED forever.

── THE DIVISION OF AUTHORITY IS PRESERVED ───────────────────────────────────
    WHETHER to ask for the address     DETERMINISTIC   this module
    WHEN to stop asking                DETERMINISTIC   this module (a budget)
    THE WORDING of the ask             GENERATED       the concierge, via the
                                                       directive below

Layer 1 stays LLM-free. A model never decides whether the visitor is ready to be
asked, and never decides that we have asked enough times.

── AND THE ASK IS GUARANTEED, NOT HOPED FOR ─────────────────────────────────
The directive makes the model ask in its own voice. ``deterministic_ask`` is the
transport- and model-independent guarantee: the turn path appends it when the
reply came back without an ask in it, exactly as it appends the client-page link.
A conversation must not dead-end because the AI engine was off.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings

logger = logging.getLogger("itrix")

# Recorded on QuestionSuggestion.target_dimension so the ask is auditable in the
# cockpit alongside the qualification questions, and so the budget below can be
# counted without a new column. It is deliberately NOT one of the ten
# LISTENING_DIMENSIONS: contact is not something we listen for, it is something we
# ask for once the listening is done.
CONTACT_DIMENSION = "contact"

# How many times we may ask before letting it go. Two, for the same reason the
# "keep this conversation" card appears once: a third ask converts an offer into
# pressure, and a visitor who has ignored two asks has answered.
DEFAULT_CONTACT_ASK_BUDGET = 2

# Reasons, mirroring reveal_bridge's vocabulary so the two read as one flow.
NO_THREAD = "no_thread"
ALREADY_HAS_LEAD = "already_has_lead"
NOT_DIAGNOSED = "not_diagnosed"
EMAIL_ALREADY_GIVEN = "email_already_given"
BUDGET_EXHAUSTED = "ask_budget_exhausted"
ASK = "ask"

# ── The approved copy bank ───────────────────────────────────────────────────
# The deterministic fallback wording, and the grounding for the directive. Written
# against the Playbook's hard language rules:
#   * it never says the address unlocks anything — reach is set by the
#     conversation, not by contact details;
#   * it never describes the page as granted, earned or approved;
#   * the second ask names the opt-out, so declining is a real option.
#
# ── WHY THE ASK NAMES BOTH DETAILS (change request, 2026-08-10) ─────────────
# The first bank asked for the address alone. In production the model, asked to
# collect what the page needs, improvised "what name or organisation should it be
# addressed to?" — and a visitor who answered exactly that question got nothing,
# because the reveal is email-anchored and the organisation cannot satisfy it.
# The ask now names both details in ONE sentence, with the email stated as the
# essential one, so the visitor can answer once and never gets asked for the
# wrong thing first. The reveal contract is unchanged: the email alone is
# sufficient, the name or organisation only enriches the page and the record.
_ASK_BANK: tuple[str, ...] = (
    "To carry out the action you selected, I need a work email for the private handoff. "
    "I’ll use it only for that action; it does not increase your disclosure access or "
    "change the stage you chose. You can decline and continue here anonymously.",
    "If you still want to continue with that identity-dependent action, a work email is "
    "the remaining handoff detail. If not, we can leave the action there and continue "
    "the public conversation without an email.",
)
# Whether a reply already contains an ask of its own. Deliberately broad: a reply
# that mentions an address at all is treated as having asked, because appending a
# second ask underneath the model's own is worse than occasionally not appending.
_MENTIONS_EMAIL = re.compile(r"e-?mail", re.IGNORECASE)


def _budget() -> int:
    return int(getattr(settings, "CONTACT_ASK_BUDGET", DEFAULT_CONTACT_ASK_BUDGET))


def asks_made(thread) -> int:
    """
    How many times this thread has already been asked for an address.

    Counted from the QuestionSuggestion rows the ask records — the same table the
    question loop uses for its own budget, so an operator auditing an unproductive
    conversation sees the qualification questions and the contact ask in one place.
    """
    if thread is None:
        return 0
    try:
        from apps.journey.models_artifacts import QuestionSuggestion

        return QuestionSuggestion.objects.filter(
            thread=thread, target_dimension=CONTACT_DIMENSION
        ).count()
    except Exception:  # noqa: BLE001 - a counting failure must never break a turn
        return 0


def evaluate(thread, body: str = "") -> dict:
    """
    Decide whether THIS turn's reply should ask for an email address.

    Returns ``{"ask": bool, "reason": str, "asks_made": int, "budget": int,
    "text": str}``. ``text`` is the approved wording for this attempt and is empty
    when ``ask`` is False.

    ── THE GATES, IN THE ORDER THEY FAIL ────────────────────────────────────
    Gate 1: there is no Lead yet. A thread with a Lead has already been revealed
            or already came in identified; either way the address is known.
    Gate 2: the qualification loop has closed (DIAGNOSED, state >= 3). This is the
            value-first rule doing its job — the diagnosis has been delivered, so
            asking is no longer asking for something before giving anything.
    Gate 3: no address has been given anywhere in the conversation yet. Accumulated
            across every visitor turn, by the same function the reveal uses, so the
            two can never disagree about whether we have one.
    Gate 4: the ask budget is not exhausted.
    """
    out = {"ask": False, "reason": "", "asks_made": 0, "budget": _budget(), "text": ""}

    if thread is None:
        out["reason"] = NO_THREAD
        return out

    if getattr(thread, "lead_id", None):
        out["reason"] = ALREADY_HAS_LEAD
        return out

    from apps.conversations.services import engagement_state, reveal_bridge, thread_state

    # Contact is never a depth/lead-capture CTA. It is permitted only after the user
    # explicitly selected an action whose execution genuinely requires identity, and
    # only after the Customer Problem Mirror has been confirmed.
    if not engagement_state.is_customer(thread):
        out["reason"] = "visitor_lane"
        return out
    if not engagement_state.identity_action_selected(thread):
        out["reason"] = "no_identity_dependent_action"
        return out
    if not engagement_state.recommendation_allowed(thread):
        out["reason"] = "problem_mirror_unconfirmed"
        return out
    if thread_state.current_state_number(thread) < 3:
        out["reason"] = NOT_DIAGNOSED
        return out

    contact = reveal_bridge.accumulated_contact(thread, extra_text=body or "")
    if contact.get("email"):
        # The reveal bridge will act on this in the same turn; nothing to ask for.
        out["reason"] = EMAIL_ALREADY_GIVEN
        return out

    made = asks_made(thread)
    out["asks_made"] = made
    if made >= out["budget"]:
        out["reason"] = BUDGET_EXHAUSTED
        return out

    out["ask"] = True
    out["reason"] = ASK
    out["text"] = _ASK_BANK[min(made, len(_ASK_BANK) - 1)]
    return out


def deterministic_ask(decision: dict) -> str:
    """The approved wording for a decision, or "" when no ask is due."""
    return (decision or {}).get("text", "") if (decision or {}).get("ask") else ""


def reply_already_asks(text: str) -> bool:
    """
    Whether a generated reply already asks for the address itself.

    Used to decide whether the deterministic wording still needs appending. The
    check is loose on purpose — see ``_MENTIONS_EMAIL``.
    """
    return bool(_MENTIONS_EMAIL.search(text or ""))


def append_ask(text: str, decision: dict) -> str:
    """
    Append the approved ask to a governed reply, unless it already contains one.

    Mirrors ``_append_client_page_link``: the model is asked to do this in its own
    words, and this is the guarantee that it happens even when the model is off,
    degraded, or simply did not comply.
    """
    ask = deterministic_ask(decision)
    if not ask:
        return text
    body = (text or "").rstrip()
    if reply_already_asks(body):
        return body
    return f"{body}\n\n{ask}" if body else ask


def record_asked(thread, decision: dict, *, message=None) -> None:
    """
    Record that the ask was PUT TO THE VISITOR, so the budget counts down.

    Called only after a DELIVERABLE reply has been persisted. An ask the visitor
    never saw — held by the guard, or lost to a degraded turn — must not consume
    the budget, or a governance hiccup would silently cost someone their page.
    """
    if thread is None or not (decision or {}).get("ask"):
        return
    try:
        from apps.agents.services import question_history

        question_history.record(
            thread,
            primary=decision.get("text", "") or _ASK_BANK[0],
            chips=[],
            target_dimension=CONTACT_DIMENSION,
            message=message,
        )
        logger.info(
            "contact ask %s/%s put to thread %s",
            int(decision.get("asks_made", 0)) + 1,
            decision.get("budget", DEFAULT_CONTACT_ASK_BUDGET),
            getattr(thread, "id", "?"),
        )
    except Exception:  # noqa: BLE001 - recording is bookkeeping, never a blocker
        logger.debug("contact ask not recorded for thread %s", getattr(thread, "id", "?"))


def directive(decision: dict) -> str:
    """Model instruction for the already-approved identity-dependent action.

    Identity is collected for the selected action only.  It never creates entitlement,
    raises disclosure, or implies that My Review is already complete/available.
    """
    if not (decision or {}).get("ask"):
        return ""
    return (
        "IDENTITY-DEPENDENT ACTION: the visitor explicitly selected an action that "
        "requires a private handoff. Answer the current turn normally, then ask in one "
        "short natural sentence for a WORK EMAIL ADDRESS needed to carry out that "
        "selected action. Say that they can decline and continue anonymously. Do not "
        "say the email unlocks content, raises disclosure, proves identity or completes "
        "a review. Do not claim a personalised page is already ready. Do not promise "
        "human follow-up unless the selected action is human follow-up. Ask for no phone "
        "number or unnecessary profile detail.\n\n"
    )
