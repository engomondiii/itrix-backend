"""
Visitor serializers.

Request bodies use the snake_case keys the web proxies already send:
``{client_id, visitor_type}`` to create a session, ``{room, visitor_type}`` for a
room entry. The session-create response includes ``id`` (what the proxy reads) plus a
few echoed fields.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.visitors.models import RoomEntry, VisitorSession, VisitorType


class VisitorSessionCreateSerializer(serializers.ModelSerializer):
    client_id = serializers.CharField(required=False, allow_blank=True, default="")
    visitor_type = serializers.ChoiceField(
        choices=VisitorType.choices,
        required=False,
        allow_blank=True,
        default=VisitorType.UNKNOWN,
    )

    class Meta:
        model = VisitorSession
        fields = ["client_id", "visitor_type", "referrer", "landing_path"]
        extra_kwargs = {
            "referrer": {"required": False, "allow_blank": True},
            "landing_path": {"required": False, "allow_blank": True},
        }

    def validate_visitor_type(self, value):
        return value or VisitorType.UNKNOWN


class VisitorSessionSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = VisitorSession
        fields = [
            "id",
            "session_id",
            "client_id",
            "visitor_type",
            "room_entry_count",
            "created_at",
        ]
        read_only_fields = fields


class RoomEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomEntry
        fields = ["room", "visitor_type"]
        extra_kwargs = {
            "visitor_type": {"required": False, "allow_blank": True},
        }

    def validate_visitor_type(self, value):
        return value or VisitorType.UNKNOWN
