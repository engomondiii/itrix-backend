"""
Result Page serializers.

Emits the exact web ``ResultPage`` shape (``itrix-web/src/types/result.types.ts``):

    leadId, productRoute, licensePathway,
    primaryTechnologies[], problemMirror, diagnosis[], alphaFitSummary,
    kpiPreview[], proofPreview[], recommendedNextStep

``licensePathway`` is null when there is no commercial pathway. ``diagnosis``,
``kpiPreview`` and ``proofPreview`` are stored already in the frontend's item shapes.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.result_page.models import ResultPage


class ResultPageSerializer(serializers.ModelSerializer):
    """
    The PUBLIC result page (AllowAny, reached by capability token).

    ── ``tier`` AND ``scoreBreakdown`` WERE REMOVED IN PHASE 3 ──────────────
    Both are on the §10.5 list of fields that must not appear in ANY payload on the
    anonymous or client plane. They were being served here to unidentified visitors —
    a visitor could read the tier we had assigned them and the breakdown of how we
    scored them, which is precisely what §4 PERSONALIZATION WITHOUT PROFILING forbids:

        Personalization means the framing, the emphasis and the chosen pathway are
        tailored. It NEVER means telling the visitor what we think we know about them.

    The page's CONTENT is still tailored by tier and score — the routing that produced
    it used both. What changed is that the visitor is no longer shown the machinery.

    Surface 2 reads the same record through a team-gated serializer where these fields
    legitimately appear.
    """

    leadId = serializers.CharField(source="lead_id", read_only=True)
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
