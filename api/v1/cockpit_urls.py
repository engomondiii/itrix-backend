"""
Cockpit routes (mounted at /api/v1/cockpit/) — TEAM PLANE ONLY.

── v7.1 PHASE 1: THE FOUR AGGREGATE MOUNTS ARE GONE FROM HERE ──────────────

This module used to mount four ANALYTICS views at cockpit/:

    cockpit/customers/    -> CustomerHealthAnalyticsView    (a distribution)
    cockpit/threads/      -> ConversationAnalyticsView      (thread metrics)
    cockpit/attachments/  -> AttachmentAnalyticsView        (attachment metrics)
    cockpit/streaming/    -> StreamingAnalyticsView         (halt telemetry)

Every one of those is ALREADY mounted under analytics/ (see apps/analytics/urls_v6.py),
so this was a second door onto the same aggregate — and the doors had misleading names.
``cockpit/threads/`` returned thread METRICS while the dashboard was asking it for a thread
LIST, and the resulting 501 guards were read as "the backend has not built this yet" when
in truth the name was occupied.

THE RULE, stated once and enforced by the layout of these two files:

    AGGREGATES under analytics/         distributions, counts, trends
    ROW-LEVEL RESOURCES under cockpit/   individual threads, customers, files, halts

So the aggregate mounts are removed here — NOT moved, because their analytics/ homes
already exist and nothing needs to change there — and the freed names are given to the
row-level resources in apps/cockpit/.

── DEPLOY ORDER MATTERS, AND IT IS THE SAFE DIRECTION ──────────────────────
The dashboard's four analytics proxies must be re-pointed at analytics/* BEFORE this ships.
Surface 2 v7.0 §03 makes that a Phase 1 MOD for exactly this reason. If they ship in the
wrong order the dashboard asks cockpit/threads/ for metrics and receives a list of rows —
a wrong answer rather than an error, which is the harder failure to notice.

If a proxy is still pointed here after this deploy, it receives row data with a `results`
key rather than a metrics object. That is a visible, immediate break rather than a subtle
one, which is the failure mode to prefer.
"""

from __future__ import annotations

from django.urls import include, path

app_name = "cockpit"

urlpatterns = [
    # The row-level resources now own these names. See apps/cockpit/urls.py.
    path("", include("apps.cockpit.urls")),
]
