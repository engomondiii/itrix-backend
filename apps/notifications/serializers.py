"""Notification serializers — emit the dashboard's Notification shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "href", "read", "createdAt"]
        read_only_fields = fields
