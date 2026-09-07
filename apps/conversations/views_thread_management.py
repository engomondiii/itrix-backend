"""Authenticated conversation management overrides for the workspace hotfix."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response

from apps.attachments.services import retention
from apps.conversations.serializers_thread import ThreadRenameSerializer, ThreadSummarySerializer
from apps.conversations.services import threads as thread_svc
from apps.conversations.views_thread import (
    ThreadDetailView,
    _client_from,
    _resolve_thread,
    _safe_error_response,
)

logger = logging.getLogger("itrix")


class AuthenticatedThreadDetailView(ThreadDetailView):
    """Keep thread reads unchanged while restricting PATCH/DELETE to signed-in owners."""

    @staticmethod
    def _managed_thread(request, thread_id):
        if _client_from(request) is None:
            return None, _safe_error_response(
                request,
                code="AUTHENTICATION_REQUIRED",
                detail="Sign in to manage conversations.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        thread = _resolve_thread(request, thread_id)
        if thread is None:
            return None, _safe_error_response(
                request,
                code="THREAD_NOT_FOUND",
                detail="This conversation is unavailable or no longer accessible.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return thread, None

    def patch(self, request, thread_id):
        thread, error = self._managed_thread(request, thread_id)
        if error is not None:
            return error

        serializer = ThreadRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        thread = thread_svc.rename(thread, serializer.validated_data["title"])
        return Response(ThreadSummarySerializer(thread).data, status=status.HTTP_200_OK)

    def delete(self, request, thread_id):
        thread, error = self._managed_thread(request, thread_id)
        if error is not None:
            return error

        try:
            retention.purge_thread(thread)
        except Exception:  # noqa: BLE001
            logger.exception("conversation delete attachment purge failed for thread %s", thread.id)
            return _safe_error_response(
                request,
                code="THREAD_DELETE_FAILED",
                detail="We could not delete that conversation just now. Please try again.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        conversation_id = thread.conversation_id
        thread.delete()
        if conversation_id:
            from apps.conversations.models import Conversation

            Conversation.objects.filter(id=conversation_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
