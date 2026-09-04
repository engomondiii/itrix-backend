"""Internal payload validation for ASTOP production-readiness state."""
from rest_framework import serializers

from apps.leads.services.readiness import READINESS_KEYS, READINESS_STATUSES


class ASTOPReadinessSerializer(serializers.Serializer):
    readiness = serializers.DictField()

    def validate_readiness(self, value):
        if not value:
            raise serializers.ValidationError("At least one readiness item is required.")
        invalid = sorted(set(value) - set(READINESS_KEYS))
        if invalid:
            raise serializers.ValidationError(f"Unknown readiness item(s): {', '.join(invalid)}")
        for key, raw in value.items():
            row = raw if isinstance(raw, dict) else {"status": raw}
            status = str(row.get("status") or "").upper()
            if status not in READINESS_STATUSES:
                raise serializers.ValidationError({key: "Invalid readiness status."})
        return value
