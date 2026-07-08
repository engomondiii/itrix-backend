"""
Agent URL routes (Phase 3 — full).

Mounted under /api/v1/agents/:
    POST agents/{key}/run/                         invoke an agent (TEAM, behind ENABLE_AGENTS)
    GET  agents/approval-queue/                    pending approvals (TEAM)
    POST agents/approval/{id}/{action}/            approve|edit|reject (governance admin)

The console/* and cockpit/* routes are mounted at the API root (see api/v1/urls.py) since
their paths are not under the agents/ prefix.
"""

from __future__ import annotations

from django.urls import path

from apps.agents.views import (
    AgentRunListView,
    AgentRunView,
    ApprovalActionView,
    ApprovalQueueView,
)

app_name = "agents"

urlpatterns = [
    path("approval-queue/", ApprovalQueueView.as_view(), name="approval-queue"),
    path("approval/<uuid:approval_id>/<str:action>/", ApprovalActionView.as_view(), name="approval-action"),
    path("runs/", AgentRunListView.as_view(), name="agent-runs"),
    path("<str:key>/run/", AgentRunView.as_view(), name="agent-run"),
]
