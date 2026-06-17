"""
Exclusive-flag handler.

Decides whether a lead involves exclusive / reserved-rights interest and what special
right (if any) applies, plus whether it should trigger the human-handoff path. Used by
the lead creator and exposed for the dashboard's exclusive-approval checklist.

Reserved-rights discipline comes from the licensing model: exclusivity is a strategic,
guardrailed pathway, so any exclusivity interest flags the lead for human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.leads.models import SpecialRights


@dataclass
class ExclusiveFlagResult:
    is_exclusive: bool
    special_rights: str
    requires_human_review: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_exclusive_flag(*, commercial_path: str | None, answers: dict, tier: int) -> ExclusiveFlagResult:
    """
    Determine exclusivity flags for a lead.

    ``commercial_path`` is the routed code (exclusive / strategic / non_exclusive / None).
    """
    reasons: list[str] = []
    path = (commercial_path or "").lower()

    is_exclusive = path in {"exclusive", "strategic"}
    special = SpecialRights.NONE.value

    if path == "strategic":
        special = SpecialRights.EXCLUSIVE_GLOBAL.value
        reasons.append("Strategic licensing interest from a high-fit organization.")
    elif path == "exclusive":
        special = SpecialRights.FIELD.value
        reasons.append("Exclusive licensing interest expressed.")

    # Tier 1 strategic leads always get human eyes.
    requires_human_review = is_exclusive or tier == 1
    if tier == 1:
        reasons.append("Tier 1 strategic lead — human concierge handoff.")

    return ExclusiveFlagResult(
        is_exclusive=is_exclusive,
        special_rights=special,
        requires_human_review=requires_human_review,
        reasons=reasons,
    )


# The 7-item exclusive-approval checklist surfaced in the dashboard.
APPROVAL_CHECKLIST_ITEMS: list[str] = [
    "Strategic fit confirmed (target industry / scale)",
    "Technical fit validated against an eligible workload",
    "NDA in place for detailed disclosure",
    "Commercial intent and budget authority verified",
    "Exclusivity scope defined (field / territory / product-category)",
    "Internal pricing & value-participation model reviewed",
    "Executive approval obtained for exclusive terms",
]


def approval_checklist() -> list[dict]:
    """Return the exclusive-approval checklist as ordered, identified items."""
    return [{"id": i + 1, "label": text, "done": False} for i, text in enumerate(APPROVAL_CHECKLIST_ITEMS)]
