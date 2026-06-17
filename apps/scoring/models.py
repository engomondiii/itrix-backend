"""Scoring models — none. Scoring is stateless logic over qualification answers."""

from __future__ import annotations

# No models: scoring is pure logic (see services/). The computed breakdown/total are
# persisted on the Lead (apps.leads) and ReviewSession (apps.review).
