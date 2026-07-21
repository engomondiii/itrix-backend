"""
Persona serializers — TEAM PLANE ONLY (Backend v6.0 §1.3).

There is deliberately NO client-plane serializer in this module, and there must never be
one. ``persona_id`` and ``pitch_room_id`` are on the §10.5 list of fields that may not
appear in any payload on the anonymous or client plane, at any state.

If a future surface needs "the pitch room for this visitor", it renders the ROOM'S
CONTENT through the artifact serializer — it does not hand over the persona record that
produced it.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.personas.models import Persona, PitchRoom


class PitchRoomSerializer(serializers.ModelSerializer):
    """TEAM. The full room, including every slide."""

    pitchRoomId = serializers.CharField(source="pitch_room_id", read_only=True)
    slideCount = serializers.IntegerField(source="slide_count", read_only=True)
    reviewStatus = serializers.CharField(source="review_status", read_only=True)

    class Meta:
        model = PitchRoom
        fields = ["id", "pitchRoomId", "title", "slides", "slideCount", "reviewStatus"]
        read_only_fields = fields


class PersonaSummarySerializer(serializers.ModelSerializer):
    """TEAM. A row in the registry browser."""

    personaId = serializers.CharField(source="persona_id", read_only=True)
    functionalFamily = serializers.CharField(source="functional_family", read_only=True)
    pitchArchetype = serializers.CharField(source="pitch_archetype", read_only=True)
    validationStatus = serializers.CharField(source="validation_status", read_only=True)
    pitchRoomId = serializers.SerializerMethodField()

    class Meta:
        model = Persona
        fields = [
            "id",
            "personaId",
            "company",
            "department",
            "primary_persona",
            "functionalFamily",
            "pitchArchetype",
            "priority",
            "validationStatus",
            "pitchRoomId",
        ]
        read_only_fields = fields

    def get_pitchRoomId(self, obj) -> str | None:
        room = getattr(obj, "pitch_room", None)
        return room.pitch_room_id if room else None


class PersonaDetailSerializer(PersonaSummarySerializer):
    """TEAM. The full persona read, including the room and the buyer-preparation notes."""

    decisionLens = serializers.CharField(source="decision_lens", read_only=True)
    departmentMandate = serializers.CharField(source="department_mandate", read_only=True)
    triggerEvent = serializers.CharField(source="trigger_event", read_only=True)
    primaryKpi = serializers.CharField(source="primary_kpi", read_only=True)
    supportingKpis = serializers.ListField(source="supporting_kpis", read_only=True)
    workloadEnvironment = serializers.CharField(source="workload_environment", read_only=True)
    boundaryWasteHypothesis = serializers.CharField(
        source="boundary_waste_hypothesis", read_only=True
    )
    desiredGain = serializers.CharField(source="desired_gain", read_only=True)
    likelyChampion = serializers.CharField(source="likely_champion", read_only=True)
    likelyBlocker = serializers.CharField(source="likely_blocker", read_only=True)
    likelyObjection = serializers.CharField(source="likely_objection", read_only=True)
    responseAngle = serializers.CharField(source="response_angle", read_only=True)
    disclosureCeiling = serializers.CharField(source="disclosure_ceiling", read_only=True)
    departmentConfidence = serializers.CharField(source="department_confidence", read_only=True)
    pitchRoom = PitchRoomSerializer(source="pitch_room", read_only=True)

    class Meta(PersonaSummarySerializer.Meta):
        fields = [
            *PersonaSummarySerializer.Meta.fields,
            "buying_role",
            "decisionLens",
            "departmentMandate",
            "triggerEvent",
            "primaryKpi",
            "supportingKpis",
            "workloadEnvironment",
            "boundaryWasteHypothesis",
            "desiredGain",
            "likelyChampion",
            "likelyBlocker",
            "likelyObjection",
            "responseAngle",
            "first_value_artifact",
            "personalized_cta",
            "commercial_route",
            "product_route",
            "disclosureCeiling",
            "departmentConfidence",
            "pitchRoom",
        ]
        read_only_fields = fields
