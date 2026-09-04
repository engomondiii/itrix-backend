"""Customer-safe serializers for a completed My Review."""
from __future__ import annotations

from rest_framework import serializers

from apps.result_page.models import ResultPage


class ResultPageSerializer(serializers.ModelSerializer):
    """Public/client-plane review.

    Internal lead ids, tiers, scores, product routing, license pathways, hidden persona
    matches and confidence/relevance bands are intentionally not part of this contract.
    """

    problemMirror = serializers.JSONField(source="problem_mirror_structured")
    alphaFitSummary = serializers.CharField(source="alpha_fit_summary")
    kpiPreview = serializers.JSONField(source="kpi_preview")
    proofPreview = serializers.JSONField(source="proof_preview")
    recommendedNextStep = serializers.CharField(source="recommended_next_step")
    generationStatus = serializers.CharField(source="generation_status", read_only=True)
    artifactFamily = serializers.CharField(source="artifact_family", read_only=True)
    artifactVersion = serializers.IntegerField(source="artifact_version", read_only=True)
    generatedAt = serializers.DateTimeField(source="generated_at", read_only=True)

    class Meta:
        model = ResultPage
        fields = [
            "problemMirror",
            "diagnosis",
            "alphaFitSummary",
            "kpiPreview",
            "proofPreview",
            "recommendedNextStep",
            "generationStatus",
            "artifactFamily",
            "artifactVersion",
            "generatedAt",
            "locale",
        ]
        read_only_fields = fields
