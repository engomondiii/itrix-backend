"""
The coverage tracker — DETERMINISTIC, LLM-FREE (Backend v6.0 §5.1, §5.2).

    Each of the TEN LISTENING DIMENSIONS carries a state of unknown, partial or covered,
    updated DETERMINISTICALLY from structured extraction of every user turn and every
    attachment.

── WHY THIS CANNOT BE A MODEL CALL ──────────────────────────────────────────
Coverage decides when the question loop STOPS. If a model decided coverage, a model would
decide when qualification ends and artifact generation begins — and a model that is
having a pleasant conversation has every incentive to keep having it.

Layer 1 stays LLM-free precisely so the loop can be TRUSTED TO TERMINATE. The language
model chooses the WORDING of a question; it never decides whether the visitor qualifies,
what state they are in, or when we have heard enough.

── WHY KEYWORDS AND NOT EMBEDDINGS ──────────────────────────────────────────
An embedding call per turn is a latency tax on the hot path AND a non-reproducible
judgement. When an operator asks "why did the loop stop after two questions?", a keyword
map gives an answer that can be read; a similarity score does not.

Coverage is INTERNAL-ONLY (§10.5): ``coverage_map`` must not appear on the anonymous or
client plane at any state.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from apps.journey.constants import LISTENING_DIMENSIONS

logger = logging.getLogger("itrix")

UNKNOWN = "unknown"
PARTIAL = "partial"
COVERED = "covered"

# Signals per dimension. Two tiers: a STRONG signal alone covers the dimension; a WEAK
# signal makes it partial, and two weak signals promote it to covered.
_SIGNALS: dict[str, dict[str, tuple[str, ...]]] = {
    "workload": {
        "strong": (r"\btraining\b", r"\binference\b", r"\bsolver\b", r"\bsimulation\b",
                   r"\bmatrix\b", r"\btensor\b", r"\bkernel\b", r"\bworkload\b",
                   r"\bmodel\b", r"\bpipeline\b", r"\bcfd\b", r"\bfea\b", r"\bpde\b"),
        "weak": (r"\bjob\b", r"\brun\b", r"\bprocess\b", r"\bcompute\b"),
    },
    "platform_environment": {
        "strong": (r"\bpytorch\b", r"\btensorflow\b", r"\bjax\b", r"\bcuda\b",
                   r"\bmatlab\b", r"\bjulia\b", r"\bansys\b", r"\bcomsol\b",
                   r"\bopenfoam\b", r"\babaqus\b", r"\bnumpy\b", r"\bscipy\b",
                   r"\bfortran\b", r"\bc\+\+\b", r"\bgpu\b", r"\bcpu\b", r"\bnpu\b",
                   r"\bhpc\b", r"\bcluster\b", r"\baws\b", r"\bazure\b", r"\bgcp\b"),
        "weak": (r"\bstack\b", r"\bplatform\b", r"\benvironment\b", r"\bframework\b"),
    },
    "pressure_area": {
        "strong": (r"\bcost\b", r"\bexpensive\b", r"\bslow\b", r"\blatency\b",
                   r"\benergy\b", r"\bpower\b", r"\bcooling\b", r"\bmemory\b",
                   r"\bbandwidth\b", r"\bunstable\b", r"\baccuracy\b", r"\bdrift\b",
                   r"\breproducib\w*\b", r"\butilization\b", r"\butilisation\b"),
        "weak": (r"\bproblem\b", r"\bissue\b", r"\bbottleneck\b", r"\bconstraint\b"),
    },
    "scale": {
        "strong": (r"\b\d+\s*(?:gpu|node|core|server|instance)s?\b",
                   r"\b\d+\s*(?:tb|gb|pb)\b", r"\bmillions?\b", r"\bbillions?\b",
                   r"\b\d+\s*(?:hour|day|week)s?\s+(?:of|per)\b", r"\bper day\b",
                   r"\bper month\b", r"\bfleet\b"),
        "weak": (r"\blarge\b", r"\bbig\b", r"\bscale\b", r"\bgrowing\b"),
    },
    "baseline": {
        "strong": (r"\bcurrently\b", r"\btoday we\b", r"\bat the moment\b",
                   r"\bbaseline\b", r"\bright now\b", r"\btakes \d+\b",
                   r"\bwe (?:use|run|have)\b"),
        "weak": (r"\bnow\b", r"\bexisting\b", r"\bcurrent\b"),
    },
    "timeline": {
        "strong": (r"\bthis (?:quarter|year|month)\b", r"\bnext (?:quarter|year|month)\b",
                   r"\bq[1-4]\b", r"\bby (?:january|february|march|april|may|june|july|"
                   r"august|september|october|november|december)\b", r"\burgent\b",
                   r"\bdeadline\b", r"\basap\b", r"\bin \d+ (?:weeks?|months?)\b"),
        "weak": (r"\bsoon\b", r"\beventually\b", r"\blater\b", r"\btimeline\b"),
    },
    "decision_process": {
        "strong": (r"\bmy team\b", r"\bwe would need\b", r"\bapproval\b",
                   r"\bprocurement\b", r"\bbudget\b", r"\bsign[- ]?off\b",
                   r"\bstakeholder\b", r"\bcto\b", r"\bvp\b", r"\bdirector\b",
                   r"\bboard\b"),
        "weak": (r"\bdecide\b", r"\bdecision\b", r"\bevaluat\w*\b"),
    },
    "success_definition": {
        "strong": (r"\bsuccess (?:would|looks?)\b", r"\bwe want to\b", r"\bgoal\b",
                   r"\bwould unlock\b", r"\bif we could\b", r"\btarget\b",
                   r"\bwe need to\b", r"\bkpi\b"),
        "weak": (r"\bimprove\b", r"\bbetter\b", r"\bfaster\b", r"\breduce\b"),
    },
    "constraint": {
        "strong": (r"\bcannot\b", r"\bcan't\b", r"\bmust (?:stay|remain|keep)\b",
                   r"\bon[- ]?prem\b", r"\bair[- ]?gap\w*\b", r"\bcompliance\b",
                   r"\bregulat\w*\b", r"\bsecurity requirement\b", r"\blocked in\b",
                   r"\blegacy\b", r"\bno budget\b"),
        "weak": (r"\bconstraint\b", r"\blimit\w*\b", r"\brestrict\w*\b"),
    },
    "commercial_intent": {
        "strong": (r"\blicens\w*\b", r"\bpartnership\b", r"\bevaluat\w*\b", r"\bpoc\b",
                   r"\bproof of concept\b", r"\bpilot\b", r"\bcontract\b",
                   r"\bprocure\w*\b", r"\bnda\b", r"\binvest\w*\b", r"\bacquisition\b"),
        "weak": (r"\bexplor\w*\b", r"\bcurious\b", r"\binterested\b", r"\blearn\b"),
    },
}

_COMPILED: dict[str, dict[str, list]] = {
    dimension: {
        tier: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        for tier, patterns in tiers.items()
    }
    for dimension, tiers in _SIGNALS.items()
}

# Which dimensions must be covered before the qualification band can close. The rest are
# useful but not required — insisting on all ten would make the loop feel like an
# interrogation, which is the failure mode §3 exists to avoid.
REQUIRED_BY_STATE: dict[int, tuple[str, ...]] = {
    1: (),
    2: ("workload", "pressure_area", "platform_environment"),
    3: ("workload", "pressure_area", "platform_environment"),
}


@dataclass
class CoverageMap:
    """Coverage across the ten dimensions. INTERNAL-ONLY."""

    dimensions: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)

    def status(self, dimension: str) -> str:
        return self.dimensions.get(dimension, UNKNOWN)

    def covered(self) -> list[str]:
        return [d for d, s in self.dimensions.items() if s == COVERED]

    def uncovered(self, required: tuple[str, ...] = ()) -> list[str]:
        pool = required or LISTENING_DIMENSIONS
        return [d for d in pool if self.dimensions.get(d, UNKNOWN) != COVERED]

    def is_complete_for(self, journey_state: int) -> bool:
        required = REQUIRED_BY_STATE.get(journey_state, ())
        if not required:
            return True
        return all(self.dimensions.get(d, UNKNOWN) == COVERED for d in required)

    def to_dict(self) -> dict:
        return {
            "dimensions": dict(self.dimensions),
            "covered_count": len(self.covered()),
            "total": len(LISTENING_DIMENSIONS),
        }


def analyse_text(text: str) -> dict[str, str]:
    """Score one piece of text against all ten dimensions."""
    result: dict[str, str] = {}
    if not (text or "").strip():
        return result

    for dimension, tiers in _COMPILED.items():
        strong_hits = sum(1 for pattern in tiers.get("strong", []) if pattern.search(text))
        weak_hits = sum(1 for pattern in tiers.get("weak", []) if pattern.search(text))

        if strong_hits >= 1:
            result[dimension] = COVERED
        elif weak_hits >= 2:
            result[dimension] = COVERED
        elif weak_hits == 1:
            result[dimension] = PARTIAL
    return result


def _merge(current: str, incoming: str) -> str:
    """
    Coverage only ever moves FORWARD.

    A later turn that mentions a dimension vaguely must not downgrade one the visitor
    already answered clearly — otherwise the loop could re-ask something it was told.
    """
    order = {UNKNOWN: 0, PARTIAL: 1, COVERED: 2}
    return current if order.get(current, 0) >= order.get(incoming, 0) else incoming


def build_for_thread(thread) -> CoverageMap:
    """
    Compute coverage from every user turn AND every attachment on the thread.

    Attachments count: a visitor who uploads their architecture doc has told us about
    their platform environment just as surely as if they had typed it.
    """
    from apps.conversations.models import Message

    coverage = CoverageMap(dimensions={d: UNKNOWN for d in LISTENING_DIMENSIONS})
    if thread is None:
        return coverage

    messages = Message.objects.filter(
        thread=thread, sender_kind__in=["visitor", "client"]
    ).order_by("seq", "created_at")

    for message in messages:
        for dimension, status in analyse_text(message.body or "").items():
            merged = _merge(coverage.dimensions.get(dimension, UNKNOWN), status)
            if merged != coverage.dimensions.get(dimension):
                coverage.dimensions[dimension] = merged
                coverage.evidence[dimension] = str(message.id)

    for text in _attachment_texts(thread):
        for dimension, status in analyse_text(text).items():
            coverage.dimensions[dimension] = _merge(
                coverage.dimensions.get(dimension, UNKNOWN), status
            )

    return coverage


def _attachment_texts(thread) -> list[str]:
    try:
        from apps.attachments.models import Attachment, AttachmentStatus

        rows = Attachment.objects.filter(
            thread=thread, status=AttachmentStatus.READY, deleted_at__isnull=True
        ).select_related("extraction")
        return [
            (row.extraction.text or "")[:20_000]
            for row in rows
            if getattr(row, "extraction", None) and row.extraction.has_text
        ]
    except Exception:  # noqa: BLE001
        return []


def snapshot(thread, review_session=None) -> CoverageMap:
    """Compute and PERSIST coverage. Returns the map."""
    coverage = build_for_thread(thread)
    try:
        from apps.journey.models_artifacts import CoverageSnapshot

        for dimension, status in coverage.dimensions.items():
            CoverageSnapshot.objects.update_or_create(
                thread=thread,
                dimension=dimension,
                defaults={
                    "status": status,
                    "evidence_message_id": coverage.evidence.get(dimension, ""),
                },
            )
    except Exception:  # noqa: BLE001
        logger.debug("coverage snapshot not persisted")
    return coverage
