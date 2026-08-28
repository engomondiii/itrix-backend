"""Governed internal handoff memo built from the confidentiality-safe conversation state."""
from __future__ import annotations

from apps.scoring.services.score_weights import CATEGORY_LABELS


def _safe(value) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    try:
        from apps.conversations.services.confidentiality import detect
        return "" if detect(text).sensitive else text
    except Exception:
        return ""  # fail closed: internal handoff is downstream generated analysis


def _fmt_breakdown(breakdown: dict) -> str:
    if not breakdown:
        return "  (no breakdown)"
    return "\n".join(
        f"  - {label}: {breakdown[key]}"
        for key, label in CATEGORY_LABELS.items()
        if key in breakdown
    ) or "  (no breakdown)"


def _fmt_answers(answers: dict) -> str:
    rows = []
    for key, value in (answers or {}).items():
        safe = _safe(value)
        if safe:
            rows.append(f"  - {key}: {safe}")
    return "\n".join(rows) or "  (no safe answers recorded)"


def generate_handoff_memo(lead) -> str:
    """Return a copy-ready internal memo without confidential/intercepted source text."""
    try:
        from apps.result_page.services.conversation_snapshot import for_lead
        snapshot = for_lead(lead)
    except Exception:
        snapshot = None

    who = _safe(getattr(lead, "company", "")) or _safe(getattr(lead, "visitor_name", "")) or "Unknown organization"
    contact = _safe(getattr(lead, "email", "")) or "(no email captured)"
    owner = _safe(getattr(getattr(lead, "owner", None), "display_name", "")) or "Unassigned"
    safe_turns = list(getattr(snapshot, "visitor_turns", []) or [])
    problem = (
        _safe(getattr(snapshot, "latest_context", ""))
        if snapshot is not None else _safe(getattr(lead, "compute_bottleneck", ""))
    )
    problem = problem or "(no non-confidential problem summary)"

    state_lines = []
    if snapshot is not None:
        state_lines = [
            f"Relationship : {snapshot.relationship_state}",
            f"Mirror       : {snapshot.mirror_status}",
            f"Action       : {snapshot.selected_action or 'none selected'}",
            f"Evaluation   : {snapshot.evaluation_type or 'none selected'}",
            f"Contract     : {snapshot.contract_stage}",
            f"Safe turns   : {len(safe_turns)}",
        ]

    return "\n".join([
        "itriX — Lead Handoff Memo",
        "=" * 32,
        f"Organization : {who}",
        f"Contact      : {contact}",
        f"Industry     : {_safe(getattr(lead, 'industry', '')) or 'n/a'}",
        f"Role         : {_safe(getattr(lead, 'role', '')) or 'n/a'}",
        *state_lines,
        "",
        f"Tier         : {lead.tier}  |  Score: {lead.score}/100",
        f"Status       : {lead.status}",
        f"Owner        : {owner}",
        f"Product route: {lead.product_route_display}",
        f"Commercial   : {lead.commercial_path_display}",
        f"Special rights: {lead.special_rights}",
        f"Human handoff: {'YES' if lead.human_handoff_trigger else 'no'}",
        "",
        "Score breakdown:", _fmt_breakdown(lead.score_breakdown),
        "",
        "Current non-confidential problem context:", f"  {problem}",
        "",
        "Qualification answers:", _fmt_answers(lead.qualification),
        "",
        "Recommended next step:", f"  {_safe(lead.recommended_next_step) or '(none)'}",
        "",
        f"Submitted: {lead.submitted_at.isoformat() if lead.submitted_at else 'n/a'}",
    ])
