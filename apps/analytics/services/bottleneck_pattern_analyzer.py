"""
Bottleneck pattern analyzer.

Finds the most common bottleneck phrases across review prompts — matches
``BottleneckPattern[] = {phrase, count}``. It uses the structured pressure-area selections
(reliable, normalized) as the primary signal, and supplements with simple keyword frequency
over the free-text prompts. This stays robust and dependency-free (no NLP libs).
"""

from __future__ import annotations

import re
from collections import Counter

from apps.review.models import ReviewSession

# Human-readable labels for the structured pressure areas.
_PRESSURE_LABELS = {
    "cost": "Cost scaling",
    "speed": "Slow runtime",
    "energy": "Energy / power limits",
    "stability_accuracy": "Stability & accuracy",
    "memory_data_movement": "Memory & data movement",
    "hardware_utilization": "Low hardware utilization",
    "architecture": "Architectural ceiling",
}

# Keyword → phrase for free-text supplementation.
_KEYWORDS = {
    "memory": "Memory pressure",
    "slow": "Slow runtime",
    "latency": "Latency",
    "cost": "Cost",
    "energy": "Energy",
    "power": "Power",
    "accuracy": "Accuracy",
    "scale": "Scaling",
    "gpu": "GPU utilization",
    "throughput": "Throughput",
    "convergence": "Convergence",
    "simulation": "Simulation cost",
}

_WORD_RE = re.compile(r"[a-zA-Z]+")


def bottleneck_patterns(*, since=None, limit: int = 10) -> list[dict]:
    counter: Counter = Counter()

    qs = ReviewSession.objects.all()
    if since:
        qs = qs.filter(created_at__gte=since)

    for session in qs.only("pressure_areas", "prompt"):
        for p in (session.pressure_areas or []):
            label = _PRESSURE_LABELS.get(p)
            if label:
                counter[label] += 1
        prompt = (session.prompt or "").lower()
        if prompt:
            words = set(_WORD_RE.findall(prompt))
            for kw, phrase in _KEYWORDS.items():
                if kw in words:
                    counter[phrase] += 1

    return [{"phrase": phrase, "count": count} for phrase, count in counter.most_common(limit)]
