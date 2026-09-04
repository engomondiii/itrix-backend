"""Focused serializers for the existing team-plane human-review workflow."""
from rest_framework import serializers


class TrustReviewDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["pass", "review", "reject"])
    rationale = serializers.CharField(allow_blank=False, trim_whitespace=True)
