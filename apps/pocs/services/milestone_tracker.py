"""
Milestone tracker.

Builds the default milestone set for a new PoC and provides a helper to update a milestone's
status within the JSON list. Milestone statuses match the dashboard's MilestoneStatus.
"""

from __future__ import annotations

_DEFAULT_MILESTONES = [
    "Kickoff & scope agreed",
    "Environment & data access set up",
    "Baseline measured",
    "ALPHA integration applied",
    "Results measured & reviewed",
    "Readout & decision",
]


def default_milestones() -> list[dict]:
    return [
        {"id": i + 1, "label": label, "status": "pending", "dueAt": None}
        for i, label in enumerate(_DEFAULT_MILESTONES)
    ]


def set_milestone_status(milestones: list[dict], milestone_id, status: str) -> list[dict]:
    for m in milestones:
        if str(m.get("id")) == str(milestone_id):
            m["status"] = status
    return milestones
