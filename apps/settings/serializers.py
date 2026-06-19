"""
Operator settings serializers.

The dashboard shapes (``itrix-dashboard/src/types/settings.ts``):

    SlaConfig         = Record<Tier, number | null>   # { "1": 24, "2": 48, "3": 24, "4": null }
    NotificationPrefs = { tier1, sla, nda, weekly }    # booleans
"""

from __future__ import annotations

from rest_framework import serializers

from apps.settings.models import NotificationPreference, SlaThresholds

# Maps the dashboard's tier-number keys <-> model column names.
_SLA_FIELDS = {
    "1": "tier1_hours",
    "2": "tier2_hours",
    "3": "tier3_hours",
    "4": "tier4_hours",
}


class SlaConfigSerializer(serializers.Serializer):
    """(De)serialize the ``{ "1": n, "2": n, "3": n, "4": n|null }`` SLA map.

    Keys are tier numbers (not valid Python identifiers), so this overrides
    ``to_representation`` / ``to_internal_value`` rather than declaring fields.
    """

    def to_representation(self, instance: SlaThresholds) -> dict:
        return {key: getattr(instance, col) for key, col in _SLA_FIELDS.items()}

    def to_internal_value(self, data) -> dict:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected an object keyed by tier.")
        validated: dict[str, int | None] = {}
        for key, value in data.items():
            if key not in _SLA_FIELDS:
                continue  # ignore unknown keys (partial PATCH-friendly)
            if value is None:
                validated[_SLA_FIELDS[key]] = None
                continue
            try:
                hours = int(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {key: "Must be a whole number of hours or null."}
                )
            if hours < 0:
                raise serializers.ValidationError({key: "Must not be negative."})
            validated[_SLA_FIELDS[key]] = hours
        return validated

    def update(self, instance: SlaThresholds, validated_data: dict) -> SlaThresholds:
        for col, value in validated_data.items():
            setattr(instance, col, value)
        instance.save(update_fields=[*validated_data.keys(), "updated_at"])
        return instance


class NotificationPrefsSerializer(serializers.ModelSerializer):
    """The ``{ tier1, sla, nda, weekly }`` toggle shape."""

    class Meta:
        model = NotificationPreference
        fields = ["tier1", "sla", "nda", "weekly"]
