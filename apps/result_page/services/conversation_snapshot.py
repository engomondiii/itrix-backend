"""Authoritative conversation snapshot for generated review artifacts.

A review is downstream of the conversation that earned it, so it must never fall back to
summarising only the first review prompt.  This module builds one deterministic, public-safe
snapshot from the durable Thread/Message spine, accepted engagement state and the originating
ReviewSession. Potentially confidential turns are excluded from artifact input rather than
repeated into a shareable review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.conversations.models import Message, SenderKind, Thread

_CORRECTION = re.compile(
    r"\b(actually|correction|to clarify|rather than|instead|not .{0,60} but|the (?:real|main) (?:issue|driver|problem)|"
    r"more specifically|정정|정확히 말하면|실제로는|대신|핵심(?:은| 문제))\b",
    re.I,
)
_DECISION = re.compile(
    r"\b(decid(?:e|ing|ed)|decision|choose|choice|whether (?:to|we|our)|roadmap|capacity plan|architecture decision|"
    r"adopt|adoption|deploy|deployment|substitut|replace|buy more|scale|rollout|commitment|"
    r"결정|선택|도입|배포|로드맵|확장)\b",
    re.I,
)
_GAP = re.compile(
    r"\b(don'?t know|do not know|unknown|not (?:yet )?measured|not instrumented|instrumentation|missing (?:data|metric|baseline)|"
    r"lack (?:data|metrics|baseline)|cannot measure|can'?t measure|need (?:a )?baseline|미측정|알 수 없|계측|기준선|데이터가 없)\b",
    re.I,
)
_KOREAN = re.compile(r"[\uac00-\ud7af]")


def _clean(text: str, limit: int = 800) -> str:
    value = " ".join((text or "").split()).strip()
    return value[:limit]


def _safe_turn(text: str) -> bool:
    try:
        from apps.conversations.services.confidentiality import detect

        return not bool(detect(text).matched)
    except Exception:  # pragma: no cover - additive safety module should be present
        return True


@dataclass
class ConversationSnapshot:
    thread: Thread | None
    locale: str = "en"
    visitor_turns: list[str] = field(default_factory=list)
    accepted_corrections: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    first_prompt: str = ""
    pressure_areas: list[str] = field(default_factory=list)
    company: str = ""
    role: str = ""
    industry: str = ""
    workload: str = ""
    mirror_status: str = "not_required"
    relationship_state: str = "visitor"
    selected_action: str = ""
    evaluation_type: str = ""
    contract_stage: str = "no_discussion"
    commitments: dict = field(default_factory=dict)

    @property
    def corpus(self) -> str:
        return "\n".join(self.visitor_turns)

    @property
    def latest_context(self) -> str:
        return " ".join(self.visitor_turns[-4:])[:2400]

    @property
    def primary_decision(self) -> str:
        return self.decisions[-1] if self.decisions else ""

    @property
    def latest_correction(self) -> str:
        return self.accepted_corrections[-1] if self.accepted_corrections else ""

    @property
    def primary_gap(self) -> str:
        return self.evidence_gaps[-1] if self.evidence_gaps else ""

    def as_agent_extra(self) -> dict:
        return {
            "conversation_snapshot": {
                "visitorTurns": self.visitor_turns[-12:],
                "acceptedCorrections": self.accepted_corrections[-8:],
                "decisions": self.decisions[-6:],
                "evidenceGaps": self.evidence_gaps[-6:],
                "relationshipState": self.relationship_state,
                "mirrorStatus": self.mirror_status,
                "selectedAction": self.selected_action,
                "evaluationType": self.evaluation_type,
                "contractStage": self.contract_stage,
                "locale": self.locale,
            }
        }


def for_lead(lead) -> ConversationSnapshot:
    """Build the highest-fidelity safe snapshot available for ``lead``."""
    thread = (
        Thread.objects.filter(lead=lead)
        .order_by("-last_activity_at", "-created_at")
        .first()
    )
    session = getattr(lead, "review_session", None)
    first_prompt = _clean(getattr(session, "prompt", "") or "")
    pressures = list(getattr(session, "pressure_areas", None) or [])

    turns: list[str] = []
    if thread is not None:
        rows = (
            Message.objects.filter(
                thread=thread,
                sender_kind__in=[SenderKind.VISITOR, SenderKind.CLIENT],
            )
            .order_by("seq", "created_at")
            .only("body", "seq")
        )
        for row in rows:
            body = _clean(row.body)
            if body and _safe_turn(body):
                turns.append(body)

    # Legacy structured review path may have no Thread. It still gets its submitted prompt,
    # but once a durable conversation exists that conversation is authoritative.
    if not turns and first_prompt and _safe_turn(first_prompt):
        turns = [first_prompt]

    corrections = [_clean(t, 500) for t in turns if _CORRECTION.search(t)]
    decisions = [_clean(t, 500) for t in turns if _DECISION.search(t)]
    gaps = [_clean(t, 500) for t in turns if _GAP.search(t)]

    locale = getattr(thread, "locale", "") if thread is not None else ""
    if not locale:
        locale = str(getattr(session, "locale", "") or "")
    if not locale:
        locale = "ko" if any(_KOREAN.search(t) for t in turns[-4:]) else "en"

    workload = (
        _clean(getattr(lead, "compute_bottleneck", "") or "", 600)
        or (turns[0] if turns else first_prompt)
    )

    return ConversationSnapshot(
        thread=thread,
        locale=locale or "en",
        visitor_turns=turns,
        accepted_corrections=corrections,
        decisions=decisions,
        evidence_gaps=gaps,
        first_prompt=first_prompt,
        pressure_areas=pressures,
        company=_clean(getattr(lead, "company", "") or "", 200),
        role=_clean(getattr(lead, "role", "") or "", 200),
        industry=_clean(getattr(lead, "industry", "") or "", 160),
        workload=workload,
        mirror_status=getattr(thread, "mirror_status", "not_required") if thread else "not_required",
        relationship_state=getattr(thread, "relationship_state", "visitor") if thread else "visitor",
        selected_action=getattr(thread, "selected_action", "") if thread else "",
        evaluation_type=getattr(thread, "evaluation_type", "") if thread else "",
        contract_stage=getattr(thread, "contract_stage", "no_discussion") if thread else "no_discussion",
        commitments=dict(getattr(thread, "conversation_commitments", None) or {}) if thread else {},
    )
