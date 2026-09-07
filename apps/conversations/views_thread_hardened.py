"""Focused hardening for transcript pagination without rewriting the thread surface."""

from __future__ import annotations

from django.db.models import Max
from rest_framework import status
from rest_framework.response import Response

from apps.conversations.models import Message
from apps.conversations.serializers_thread import ThreadTurnSerializer
from apps.conversations.views_thread import (
    ThreadMessagesView as BaseThreadMessagesView,
    _resolve_thread,
    _safe_error_response,
)


def latest_seq_for_thread(thread) -> int:
    """Compute latest sequence in one DB aggregate, never by materializing every turn."""
    value = Message.objects.filter(thread=thread).aggregate(latest=Max("seq"))["latest"]
    return int(value or 0)


def _parse_limit(request):
    raw = request.query_params.get("limit", "200")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 500 else None


class ThreadMessagesView(BaseThreadMessagesView):
    """Transcript endpoint with bounded limit validation and O(1)-query latestSeq."""

    def get(self, request, thread_id):
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return _safe_error_response(
                request,
                code="THREAD_NOT_FOUND_OR_INACCESSIBLE",
                detail="Conversation not found or unavailable.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            after = int(request.query_params.get("after_seq", 0))
        except (TypeError, ValueError):
            after = 0

        limit = _parse_limit(request)
        if limit is None:
            return _safe_error_response(
                request,
                code="INVALID_TRANSCRIPT_LIMIT",
                detail="limit must be an integer between 1 and 500.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        qs = Message.objects.filter(thread=thread, seq__gt=after).order_by("seq", "created_at")[:limit]
        return Response(
            {
                "threadId": str(thread.id),
                "messages": ThreadTurnSerializer(qs, many=True).data,
                "latestSeq": latest_seq_for_thread(thread),
            },
            status=status.HTTP_200_OK,
        )
