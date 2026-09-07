"""Portal conversation messaging with explicit safe failure taxonomy."""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from apps.clients.views import PortalConversationMessagesView as LegacyPortalConversationMessagesView

logger = logging.getLogger("itrix")


class PortalConversationMessagesView(LegacyPortalConversationMessagesView):
    """Keep the existing GET contract; harden only the message-send failure path."""

    def post(self, request, conversation_id):
        from apps.conversations.models import (
            Conversation,
            ConversationContext,
            MessageTooLong,
        )
        from apps.conversations.serializers import MessageSerializer
        from apps.conversations.services import ingest
        from apps.conversations.services.history import ensure_portal_thread

        client = request.user
        conv = get_object_or_404(
            Conversation,
            id=conversation_id,
            client=client,
            context__in=[ConversationContext.PORTAL, ConversationContext.CUSTOMER_SUCCESS],
        )

        body = (request.data.get("body") or "").strip()
        attachment_ids = request.data.get("attachmentIds") or []
        if not isinstance(attachment_ids, list):
            attachment_ids = []
        attachment_ids = [str(a) for a in attachment_ids][:8]
        if not body and not attachment_ids:
            return Response(
                {"detail": "A message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        thread = ensure_portal_thread(conv, client)
        request_id = str(getattr(request, "correlation_id", "") or "")
        try:
            message = ingest.ingest_inbound(
                conv,
                sender_kind="client",
                body=body,
                client=client,
                thread=thread,
                meta={"attachment_ids": attachment_ids},
            )
        except MessageTooLong as exc:
            payload = {
                "detail": str(exc),
                "code": "MESSAGE_TOO_LONG",
            }
            if request_id:
                payload["requestId"] = request_id
            return Response(payload, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        except Exception:  # noqa: BLE001 - unknown failure must never leak or masquerade as 413
            logger.exception(
                "portal.message_ingest_failed conversation=%s request_id=%s",
                conversation_id,
                request_id or "unknown",
            )
            payload = {
                "detail": "We could not send that message just now. Please try again.",
                "code": "PORTAL_MESSAGE_UNAVAILABLE",
            }
            if request_id:
                payload["requestId"] = request_id
            return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if attachment_ids:
            try:
                ingest.associate_attachments(message, attachment_ids)
            except Exception:  # noqa: BLE001 - attachment association is part of this send
                logger.exception(
                    "portal.message_attachment_association_failed message=%s request_id=%s",
                    getattr(message, "id", "?"),
                    request_id or "unknown",
                )
                payload = {
                    "detail": "We could not finish sending that message just now. Please try again.",
                    "code": "PORTAL_MESSAGE_UNAVAILABLE",
                }
                if request_id:
                    payload["requestId"] = request_id
                return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)
