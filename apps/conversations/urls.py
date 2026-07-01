"""
Conversation URL routes (mounted under /api/v1/conversations/) — TEAM.

Client-facing conversation reads live under portal/* (apps.clients.urls). These team
routes let the console + admins inspect threads.
"""

from __future__ import annotations

from django.urls import path

from apps.conversations.views import TeamConversationDetailView, TeamConversationListView

app_name = "conversations"

urlpatterns = [
    path("", TeamConversationListView.as_view(), name="conversation-list"),
    path("<uuid:conversation_id>/", TeamConversationDetailView.as_view(), name="conversation-detail"),
]
