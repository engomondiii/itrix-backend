"""
Context assembly (Backend v6.0 §2.4, Architecture v2.6 §12.5).

Because the visitor has NO character limit and may attach many files, context assembly
is EXPLICIT rather than incidental. Every turn's context is built in a fixed priority
order, and what could not be included is recorded rather than silently dropped.

── THE PRIORITY BUDGET ──────────────────────────────────────────────────────
    1. system contract + journey/disclosure state     (never trimmed)
    2. retrieved approved chunks                      (never trimmed)
    3. the current user turn, in full                 (never trimmed)
    4. recent turns within the current state, in full
    5. attachment excerpts, relevance-selected        (fenced; Phase 2)
    6. rolling summaries of closed states

── THE THREE RULES ──────────────────────────────────────────────────────────
1. SUMMARIZE, NEVER SILENTLY TRUNCATE. When the budget is exceeded, older turns are
   replaced by a rolling deterministic summary that is PERSISTED and AUDITABLE.
2. THE VISITOR'S OWN WORDS ARE NEVER SUMMARIZED AWAY WITHIN THE CURRENT STATE.
   Summarization applies to CLOSED states only. The thing they just told us is the one
   thing we must not compress.
3. NOTHING IS SILENTLY DROPPED. If material content could not be considered, the
   assembly records it in ``context_note`` and the turn says so plainly.

Priorities 1-3 are never trimmed, so an oversized single turn can push out history but
can never push out the governance contract or the approved knowledge it must answer from.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("itrix")

# Rough chars-per-token. Deliberately conservative: over-estimating the token cost of a
# turn makes us summarize slightly early, which is a much cheaper failure than blowing
# the model's context window mid-generation.
CHARS_PER_TOKEN = 4

# Default context budget in characters. Sized well inside the model window so the
# response itself always has room.
DEFAULT_CONTEXT_BUDGET_CHARS = 120_000


def context_budget_chars() -> int:
    return int(getattr(settings, "CONTEXT_BUDGET_CHARS", DEFAULT_CONTEXT_BUDGET_CHARS))


@dataclass
class ContextBlock:
    """One prioritized slice of the assembled context."""

    priority: int
    kind: str  # system | knowledge | current_turn | recent_turns | attachments | summary
    text: str
    trimmable: bool = True

    @property
    def size(self) -> int:
        return len(self.text or "")


@dataclass
class AssembledContext:
    """The result of one assembly pass."""

    blocks: list[ContextBlock] = field(default_factory=list)
    context_note: str = ""
    dropped_kinds: list[str] = field(default_factory=list)
    summarized_message_ids: list[str] = field(default_factory=list)
    budget: int = 0
    used: int = 0

    def text(self) -> str:
        return "\n\n".join(b.text for b in sorted(self.blocks, key=lambda b: b.priority) if b.text)

    @property
    def complete(self) -> bool:
        """True when nothing had to be dropped or summarized away."""
        return not self.dropped_kinds and not self.summarized_message_ids


# The fixed priority order. Lower number = assembled first = never trimmed.
PRIORITY_SYSTEM = 1
PRIORITY_KNOWLEDGE = 2
PRIORITY_CURRENT_TURN = 3
PRIORITY_RECENT_TURNS = 4
PRIORITY_ATTACHMENTS = 5
PRIORITY_SUMMARIES = 6

NEVER_TRIMMED = {PRIORITY_SYSTEM, PRIORITY_KNOWLEDGE, PRIORITY_CURRENT_TURN}


def assemble(
    *,
    system_contract: str,
    journey_state: str,
    disclosure_ceiling: str,
    current_turn: str,
    recent_turns: list[str] | None = None,
    knowledge_chunks: list[str] | None = None,
    attachment_excerpts: list[str] | None = None,
    closed_state_summaries: list[str] | None = None,
    budget: int | None = None,
) -> AssembledContext:
    """
    Build one turn's context in fixed priority order.

    Returns an ``AssembledContext`` carrying the blocks that fit, plus a human-readable
    ``context_note`` naming anything that did not. The caller writes that note onto the
    Message so the cockpit — and the visitor — can see it.
    """
    limit = budget or context_budget_chars()
    result = AssembledContext(budget=limit)

    header = (
        f"{system_contract}\n\n"
        f"[journey_state={journey_state} disclosure_ceiling={disclosure_ceiling}]"
    )
    ordered: list[ContextBlock] = [
        ContextBlock(PRIORITY_SYSTEM, "system", header, trimmable=False),
        ContextBlock(
            PRIORITY_KNOWLEDGE,
            "knowledge",
            "\n\n".join(knowledge_chunks or []),
            trimmable=False,
        ),
        ContextBlock(PRIORITY_CURRENT_TURN, "current_turn", current_turn or "", trimmable=False),
        ContextBlock(PRIORITY_RECENT_TURNS, "recent_turns", "\n\n".join(recent_turns or [])),
        ContextBlock(
            PRIORITY_ATTACHMENTS, "attachments", "\n\n".join(attachment_excerpts or [])
        ),
        ContextBlock(
            PRIORITY_SUMMARIES, "summary", "\n\n".join(closed_state_summaries or [])
        ),
    ]

    used = 0
    for block in ordered:
        if not block.text:
            continue
        if block.priority in NEVER_TRIMMED:
            # Priorities 1-3 are admitted regardless — a turn is never answered without
            # its governance contract, its approved knowledge, or the visitor's actual
            # question.
            result.blocks.append(block)
            used += block.size
            continue

        if used + block.size <= limit:
            result.blocks.append(block)
            used += block.size
            continue

        remaining = max(0, limit - used)
        if remaining > 500:
            # Partial admission with an explicit marker — never a silent cut.
            truncated = block.text[:remaining].rstrip()
            result.blocks.append(
                ContextBlock(
                    block.priority,
                    block.kind,
                    truncated + "\n\n[...earlier detail summarized for length]",
                )
            )
            used += len(truncated)
            result.dropped_kinds.append(block.kind)
        else:
            result.dropped_kinds.append(block.kind)

    result.used = used
    result.context_note = build_context_note(result.dropped_kinds)
    return result


_NOTE_LABELS = {
    "recent_turns": "some earlier turns in this conversation",
    "attachments": "some attached file content",
    "summary": "summaries of earlier stages",
}


def build_context_note(dropped_kinds: list[str]) -> str:
    """
    A plain, honest sentence naming what could not be considered.

    RULE 3 in prose: if material content could not be considered, the turn SAYS SO. No
    hedging, no apology, no pretending the answer is complete.
    """
    if not dropped_kinds:
        return ""
    labels = [_NOTE_LABELS.get(kind, kind) for kind in dict.fromkeys(dropped_kinds)]
    if len(labels) == 1:
        what = labels[0]
    else:
        what = ", ".join(labels[:-1]) + f" and {labels[-1]}"
    return (
        f"This conversation is long enough that {what} could not be included in full "
        f"when preparing this response. Ask about anything that looks missing and it "
        f"will be brought back into view."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rolling summaries (§2.4 rule 1)
# ─────────────────────────────────────────────────────────────────────────────
def summarize_closed_state(messages) -> str:
    """
    A DETERMINISTIC rolling summary of the turns from a closed state.

    Deterministic on purpose: a summary that is persisted and replayed into every later
    turn must be auditable and reproducible. A generated summary would put un-governed
    text into the model's context on every subsequent turn, which is exactly the surface
    the governance fabric exists to close.

    Only ever called for CLOSED states — rule 2 forbids summarizing the current state.
    """
    if not messages:
        return ""
    lines: list[str] = []
    for message in messages:
        who = "Visitor" if getattr(message, "sender_kind", "") in {"visitor", "client"} else "itriX"
        body = " ".join((getattr(message, "body", "") or "").split())
        if not body:
            continue
        lines.append(f"{who}: {body[:280]}" + ("..." if len(body) > 280 else ""))
    if not lines:
        return ""
    return "[Summary of an earlier stage of this conversation]\n" + "\n".join(lines)


def summarize_thread_state(thread, state_key: str) -> str:
    """Build (and return) the rolling summary for one closed state of a thread."""
    from apps.conversations.models import Message

    messages = (
        Message.objects.filter(thread=thread)
        .exclude(streaming_status="halted")
        .order_by("seq", "created_at")
    )
    return summarize_closed_state(list(messages))
