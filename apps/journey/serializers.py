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
    # v6.0 Phase 3: the NBA and every other ask arrive as INLINE CARDS. The rails fields
    # are gone — see apps/conversations/serializers_thread.py RETIRED_FIELDS.
    cards = serializers.ListField(child=serializers.DictField(), default=list)


class JourneyTransitionSerializer(serializers.ModelSerializer):
    at = serializers.DateTimeField(source="created_at", read_only=True)
    fromState = serializers.CharField(source="from_state", read_only=True)
    toState = serializers.CharField(source="to_state", read_only=True)

    class Meta:
        model = JourneyTransition
        fields = ["id", "fromState", "toState", "event", "reveal", "meta", "at"]
        read_only_fields = fields


class JourneyLeadSerializer(serializers.Serializer):
    """
    Team-facing (Surface 2) view of a lead's journey + its transition history.

    ── v7.1 PHASE 1: THIS PAYLOAD NOW CARRIES ``shell`` ────────────────────
    THE HIGHEST-PRIORITY CORRECTION IN THIS PHASE, and it is a production crash rather
    than a missing feature.

    The dashboard's lead-detail page renders a shell-contract panel. It reads
    ``payload.shell`` and, finding nothing, threw. It does NOT derive the contract
    locally, and that is deliberate rather than an oversight: the dashboard authenticates
    on its own team-JWT, so anything it derived would be its own opinion of what a visitor
    may see rather than the server's. An oversight panel that shows a contract the visitor
    is not actually on is worse than a panel that shows nothing.

    So the fix belongs here. ``shell`` is the same structure Surface 1 receives, built by
    the same ``services/shell.py`` — one builder, one answer, whoever is asking.

    It is ``allow_null`` because a Lead with no thread has no shell to describe, and a
    null is honest where an invented empty contract would not be.
    """

    leadId = serializers.CharField()
    state = serializers.CharField()
    valueDelivered = serializers.BooleanField()
    accountInviteAvailable = serializers.BooleanField()
    transitions = JourneyTransitionSerializer(many=True)
    # v7.1 Phase 1 — see the note above. Not derived by the client, ever.
    shell = serializers.DictField(allow_null=True, required=False)


class AdvanceRequestSerializer(serializers.Serializer):
    """Body for ``POST journey/leads/{id}/advance/`` (team-guarded)."""

    event = serializers.ChoiceField(choices=[e.value for e in JourneyEvent])
    meta = serializers.DictField(required=False, default=dict)

    def validate_event(self, value: str) -> str:
        if value not in {e.value for e in JourneyEvent}:
            raise serializers.ValidationError("Unknown journey event.")
        return value
