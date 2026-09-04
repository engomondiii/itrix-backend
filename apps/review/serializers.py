"""
Review serializers.

Request shapes match exactly what the web proxies send
(``itrix-web/src/app/api/review/*``):

    create:  { client_id, visitor_type }              -> { id, ... }
    prompt:  { prompt, pressure_areas, environment }  -> { sessionId, immediateResponse }
    qualify: { answers }                              -> customer-safe generation acknowledgement
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.validators import MAX_PROMPT_LENGTH
from apps.review.models import ReviewSession


class ReviewSessionCreateSerializer(serializers.Serializer):
    client_id = serializers.CharField(required=False, allow_blank=True, default="")
    visitor_type = serializers.CharField(required=False, allow_blank=True, default="unknown")
    locale = serializers.ChoiceField(choices=("en", "ko"), required=False, default="en")
    visitor_session_id = serializers.UUIDField(required=False, allow_null=True)


class ReviewSessionSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = ReviewSession
        fields = ["id", "session_id", "status", "locale", "created_at"]
        read_only_fields = fields


class PromptSubmitSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=MAX_PROMPT_LENGTH, allow_blank=False)
    pressure_areas = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    environment = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=""
    )


class QualifySubmitSerializer(serializers.Serializer):
    answers = serializers.DictField(child=serializers.JSONField(), required=True)

    def validate_answers(self, value):
        if not value:
            raise serializers.ValidationError("Qualification answers are required.")
        return value
