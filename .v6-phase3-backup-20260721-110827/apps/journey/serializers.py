"""Journey serializers — the shapes Surface 1 (public, token) and Surface 2 consume."""

from __future__ import annotations

from rest_framework import serializers

from apps.journey.models import JourneyEvent, JourneyState, JourneyTransition


class JourneyStateSerializer(serializers.Serializer):
    """
    The public journey payload returned by ``GET journey/{token}/``:
    the current state, the authorized surface, whether value was delivered, whether the
    account invite is available, and any active reveals.
    """

    state = serializers.CharField()
    authorizedSurface = serializers.CharField(allow_null=True)
    valueDelivered = serializers.BooleanField()
    accountInviteAvailable = serializers.BooleanField()
    reveals = serializers.ListField(child=serializers.DictField(), default=list)


class JourneyTransitionSerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at", read_only=True)
    fromState = serializers.CharField(source="from_state", read_only=True)
    toState = serializers.CharField(source="to_state", read_only=True)

    class Meta:
        model = JourneyTransition
        fields = ["id", "fromState", "toState", "event", "reveal", "meta", "at"]
        read_only_fields = fields


class JourneyLeadSerializer(serializers.Serializer):
    """Team-facing (Surface 2) view of a lead's journey + its transition history."""

    leadId = serializers.CharField()
    state = serializers.CharField()
    valueDelivered = serializers.BooleanField()
    accountInviteAvailable = serializers.BooleanField()
    transitions = JourneyTransitionSerializer(many=True)


class AdvanceRequestSerializer(serializers.Serializer):
    """Body for ``POST journey/leads/{id}/advance/`` (team-guarded)."""

    event = serializers.ChoiceField(choices=[e.value for e in JourneyEvent])
    meta = serializers.DictField(required=False, default=dict)

    def validate_event(self, value: str) -> str:
        if value not in {e.value for e in JourneyEvent}:
            raise serializers.ValidationError("Unknown journey event.")
        return value
