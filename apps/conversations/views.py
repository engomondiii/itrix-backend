"""
Conversation views.

Phase 2 exposes conversation reads through the client portal (see apps.clients.views for
the portal/* mounts, which call the history helpers). This module provides a small
TEAM-facing read surface so the S2 console (Phase 3) and admins can inspect threads. The
client-facing conversation list/detail is served under portal/* to keep the client-JWT
plane's routes together.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.conversations.models import Conversation
from apps.conversations.serializers import (
    ConversationSummarySerializer,
    ConversationThreadSerializer,
)
from apps.core.permissions import IsDashboardUser


class TeamConversationListView(APIView):
    """GET conversations/ — TEAM. All active conversations (console overview)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request):
        qs = Conversation.objects.filter(is_active=True).order_by("-last_message_at")[:200]
        return Response(ConversationSummarySerializer(qs, many=True).data)


class TeamConversationDetailView(APIView):
    """GET conversations/{id}/ — TEAM. A full thread (includes held drafts via team view)."""

    permission_classes = [IsAuthenticated, IsDashboardUser]

    def get(self, request, conversation_id):
        conv = get_object_or_404(Conversation, id=conversation_id)
        return Response(ConversationThreadSerializer(conv).data)
