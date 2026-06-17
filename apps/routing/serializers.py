"""Routing serializers (used by the internal preview endpoint)."""

from __future__ import annotations

from rest_framework import serializers


class RoutingPreviewSerializer(serializers.Serializer):
    """Validate an answers dict for a routing preview."""

    answers = serializers.DictField(child=serializers.JSONField(), required=True)


class RoutingResultSerializer(serializers.Serializer):
    product_route = serializers.CharField()
    license_pathway = serializers.CharField(allow_null=True)
