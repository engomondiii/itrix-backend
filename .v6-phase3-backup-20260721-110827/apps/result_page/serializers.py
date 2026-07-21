"""
Result Page serializers.

Emits the exact web ``ResultPage`` shape (``itrix-web/src/types/result.types.ts``):

    leadId, tier, scoreBreakdown, productRoute, licensePathway,
    primaryTechnologies[], problemMirror, diagnosis[], alphaFitSummary,
    kpiPreview[], proofPreview[], recommendedNextStep

``licensePathway`` is null when there is no commercial pathway. ``diagnosis``,
``kpiPreview`` and ``proofPreview`` are stored already in the frontend's item shapes.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.result_page.models import ResultPage


class ResultPageSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    scoreBreakdown = serializers.JSONField(source="score_breakdown")
    productRoute = serializers.CharField(source="product_route")
    licensePathway = serializers.SerializerMethodField()
    primaryTechnologies = serializers.ListField(
        source="primary_technologies", child=serializers.CharField()
    )
    problemMirror = serializers.CharField(source="problem_mirror")
    alphaFitSummary = serializers.CharField(source="alpha_fit_summary")
    kpiPreview = serializers.JSONField(source="kpi_preview")
    proofPreview = serializers.JSONField(source="proof_preview")
    recommendedNextStep = serializers.CharField(source="recommended_next_step")
    usedAi = serializers.BooleanField(source="used_ai", read_only=True)

    class Meta:
        model = ResultPage
        fields = [
            "leadId",
            "tier",
            "scoreBreakdown",
            "productRoute",
            "licensePathway",
            "primaryTechnologies",
            "problemMirror",
            "diagnosis",
            "alphaFitSummary",
            "kpiPreview",
            "proofPreview",
            "recommendedNextStep",
            "usedAi",
        ]
        read_only_fields = fields

    def get_licensePathway(self, obj) -> str | None:
        return obj.license_pathway or None
