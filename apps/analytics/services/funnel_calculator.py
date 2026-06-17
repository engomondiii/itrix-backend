"""
Funnel calculator.

Builds the conversion funnel as ordered stages with counts and stage-to-stage conversion
(0–1) — matches ``FunnelStage[] = {stage, count, conversion?}``. The funnel walks the lead
lifecycle: all leads → contacted+ → meeting/NDA+ → evaluation/PoC+ → licensed.

Counts are cumulative "reached this stage or beyond", so conversion is monotonic and
interpretable as funnel drop-off.
"""

from __future__ import annotations

from apps.leads.models import Lead

# Lifecycle order used to decide whether a lead has "reached" a stage.
_STATUS_ORDER = {
    "New": 0,
    "Qualifying": 0,
    "Contacted": 1,
    "Nurture": 1,
    "Meeting Booked": 2,
    "NDA": 3,
    "Evaluation": 4,
    "PoC": 5,
    "Negotiation": 6,
    "Licensed": 7,
    "Closed": 7,
    "Lost": 0,
}

# The funnel stages we report, with the minimum lifecycle rank that counts as "reached".
_FUNNEL = [
    ("Submitted", 0),
    ("Contacted", 1),
    ("Meeting / NDA", 2),
    ("Evaluation / PoC", 4),
    ("Licensed", 7),
]


def funnel(*, since=None) -> list[dict]:
    qs = Lead.objects.all()
    if since:
        qs = qs.filter(submitted_at__gte=since)
    ranks = [_STATUS_ORDER.get(s, 0) for s in qs.values_list("status", flat=True)]
    total = len(ranks)

    stages: list[dict] = []
    prev_count: int | None = None
    for label, min_rank in _FUNNEL:
        count = sum(1 for r in ranks if r >= min_rank) if min_rank > 0 else total
        stage = {"stage": label, "count": count}
        if prev_count is not None:
            stage["conversion"] = round(count / prev_count, 3) if prev_count else 0.0
        stages.append(stage)
        prev_count = count
    return stages
