"""
Visitor views (PUBLIC — Surface 1, no auth).

    POST /api/v1/visitors/sessions/                 create a session  -> {id, ...}
    POST /api/v1/visitors/sessions/{id}/room-entry/ record a room visit

Both are best-effort, abuse-throttled, and resilient: the public site degrades
gracefully if these fail, so they should virtually never error on well-formed input.
"""

from __future__ import annotations

import hashlib
import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.visitors.models import RoomEntry, VisitorSession
from apps.visitors.serializers import (
    RoomEntrySerializer,
    VisitorSessionCreateSerializer,
    VisitorSessionSerializer,
)

logger = logging.getLogger("itrix")


def _hash_ip(request) -> str:
    """Return a salted hash of the client IP — never store the raw address."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")) or ""
    if not ip:
        return ""
    # Salt with SECRET_KEY so hashes aren't reversible via a rainbow table.
    from django.conf import settings

    return hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()[:32]


class VisitorSessionCreateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request):
        serializer = VisitorSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = serializer.save(
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
            ip_hash=_hash_ip(request),
            referrer=(request.data.get("referrer") or "")[:512],
            landing_path=(request.data.get("landing_path") or "")[:512],
        )
        logger.info("VisitorSession created: %s", session.id)
        return Response(
            VisitorSessionSerializer(session).data, status=status.HTTP_201_CREATED
        )


class RoomEntryView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request, session_id):
        session = get_object_or_404(VisitorSession, pk=session_id)
        serializer = RoomEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        RoomEntry.objects.create(
            session=session,
            room=serializer.validated_data["room"],
            visitor_type=serializer.validated_data.get("visitor_type") or session.visitor_type,
        )
        # Keep the session's coarse type fresh if the room implies one.
        vt = serializer.validated_data.get("visitor_type")
        if vt and session.visitor_type in ("", "unknown"):
            session.visitor_type = vt
            session.save(update_fields=["visitor_type", "updated_at"])
        session.register_room_entry()

        return Response(
            {"ok": True, "session_id": str(session.id)}, status=status.HTTP_201_CREATED
        )
