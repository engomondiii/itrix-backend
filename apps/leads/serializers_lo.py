"""Internal payload validation for governed ASTOP License-Out terms."""
from rest_framework import serializers

from apps.leads.models import SpecialRights


class GovernedLOTermsSerializer(serializers.Serializer):
    rights = serializers.DictField()
    economics = serializers.DictField()
    status = serializers.ChoiceField(choices=["draft", "negotiated", "final"])
    source_reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)

    def validate_rights(self, value):
        if not value:
            raise serializers.ValidationError("A non-empty rights structure is required.")
        rights_type = value.get("rights_type")
        if rights_type not in set(SpecialRights.values):
            raise serializers.ValidationError("rights_type must reference the existing SpecialRights vocabulary.")
        return value

    def validate_economics(self, value):
        if not value:
            raise serializers.ValidationError("A non-empty economics structure is required.")
        return value
