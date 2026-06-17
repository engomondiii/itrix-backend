"""
Analytics serializers.

The analytics payload is assembled from plain dicts produced by the services, so the view
returns them directly. This serializer documents the snapshot model for admin/history use.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.analytics.models import MetricSnapshot


class MetricSnapshotSerializer(serializers.ModelSerializer):
    capturedFor = serializers.DateField(source="captured_for", read_only=True)

    class Meta:
        model = MetricSnapshot
        fields = ["id", "capturedFor", "new_leads", "tier1_count", "tier2_count", "overdue_follow_ups", "payload"]
        read_only_fields = fields
