"""
Handoff memo generator.

Builds the offline handoff memo for ``GET leads/{id}/handoff/`` — a plain-text brief a
team member can copy when handing a lead to a colleague or taking it offline. It pulls
together identity, score/tier, routing, the bottleneck summary, qualification answers,
and the recommended next step. Deterministic and dependency-free.
"""

from __future__ import annotations

from apps.scoring.services.score_weights import CATEGORY_LABELS


def _fmt_breakdown(breakdown: dict) -> str:
    if not breakdown:
        return "  (no breakdown)"
    lines = []
    for key, label in CATEGORY_LABELS.items():
        if key in breakdown:
            lines.append(f"  - {label}: {breakdown[key]}")
    return "\n".join(lines)


def _fmt_answers(answers: dict) -> str:
    if not answers:
        return "  (no answers recorded)"
    return "\n".join(f"  - {k}: {v}" for k, v in answers.items())


def generate_handoff_memo(lead) -> str:
    """Return a copy-ready plaintext handoff memo for ``lead``."""
    who = lead.company or lead.visitor_name or "Unknown organization"
    contact = lead.email or "(no email captured)"
    owner = lead.owner.display_name if lead.owner else "Unassigned"

    return "\n".join(
        [
            "iTrix — Lead Handoff Memo",
            "=" * 32,
            f"Organization : {who}",
            f"Contact      : {contact}",
            f"Industry     : {lead.industry or 'n/a'}",
            f"Role         : {lead.role or 'n/a'}",
            "",
            f"Tier         : {lead.tier}  |  Score: {lead.score}/100",
            f"Status       : {lead.status}",
            f"Owner        : {owner}",
            f"Product route: {lead.product_route_display}",
            f"Commercial   : {lead.commercial_path_display}",
            f"Special rights: {lead.special_rights}",
            f"Human handoff: {'YES' if lead.human_handoff_trigger else 'no'}",
            "",
            "Score breakdown:",
            _fmt_breakdown(lead.score_breakdown),
            "",
            "Compute bottleneck (summary):",
            f"  {lead.compute_bottleneck or '(none)'}",
            "",
            "Qualification answers:",
            _fmt_answers(lead.qualification),
            "",
            "Recommended next step:",
            f"  {lead.recommended_next_step or '(none)'}",
            "",
            f"Submitted: {lead.submitted_at.isoformat() if lead.submitted_at else 'n/a'}",
        ]
    )
