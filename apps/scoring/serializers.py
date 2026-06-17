"""Scoring serializers (used by the internal preview endpoint)."""

from __future__ import annotations

from rest_framework import serializers


class ScorePreviewSerializer(serializers.Serializer):
    answers = serializers.DictField(child=serializers.JSONField(), required=True)
