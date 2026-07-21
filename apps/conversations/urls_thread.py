"""
Thread routes (mounted at /api/v1/threads/) — PUBLIC, session-scoped.

    POST   threads/
    GET    threads/
    GET    threads/{id}/
    PATCH  threads/{id}/
    DELETE threads/{id}/
    GET    threads/{id}/shell/
    GET    threads/{id}/messages/
    POST   threads/{id}/turns/

Order matters: the sub-resource routes are declared BEFORE the bare ``{id}/`` route so
they are not swallowed by it.
"""

from __future__ import annotations

from django.urls import path

from apps.conversations.views_thread import (
    ThreadDetailView,
    ThreadListCreateView,
    ThreadMessagesView,
    ThreadShellView,
    ThreadTurnsView,
)

app_name = "threads"

urlpatterns = [
    path("", ThreadListCreateView.as_view(), name="thread-list-create"),
    path("<uuid:thread_id>/turns/", ThreadTurnsView.as_view(), name="thread-turns"),
    path("<uuid:thread_id>/messages/", ThreadMessagesView.as_view(), name="thread-messages"),
    path("<uuid:thread_id>/shell/", ThreadShellView.as_view(), name="thread-shell"),
    path("<uuid:thread_id>/", ThreadDetailView.as_view(), name="thread-detail"),
]
