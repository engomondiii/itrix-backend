"""
Thread routes (mounted at /api/v1/threads/) — PUBLIC, session-scoped.

Order matters: sub-resource routes are declared before the bare ``{id}/`` route.
"""

from __future__ import annotations

from django.urls import path

from apps.conversations.views_thread import (
    ThreadDetailView,
    ThreadListCreateView,
    ThreadPaneView,
    ThreadShellView,
    ThreadTurnsView,
    ThreadRetryView,
)
from apps.conversations.views_thread_hardened import ThreadMessagesView

app_name = "threads"

urlpatterns = [
    path("", ThreadListCreateView.as_view(), name="thread-list-create"),
    path("<uuid:thread_id>/turns/", ThreadTurnsView.as_view(), name="thread-turns"),
    path("<uuid:thread_id>/retry/", ThreadRetryView.as_view(), name="thread-retry"),
    path("<uuid:thread_id>/messages/", ThreadMessagesView.as_view(), name="thread-messages"),
    path("<uuid:thread_id>/shell/", ThreadShellView.as_view(), name="thread-shell"),
    path("<uuid:thread_id>/pane/", ThreadPaneView.as_view(), name="thread-pane"),
    path("<uuid:thread_id>/", ThreadDetailView.as_view(), name="thread-detail"),
]
