"""Evaluation serializers — emit the dashboard's Evaluation shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.evaluations.models import Evaluation


class EvaluationSerializer(serializers.ModelSerializer):
    leadId = serializers.CharField(source="lead_id", read_only=True)
    leadName = serializers.CharField(source="lead_name")
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Evaluation
        fields = [
            "id", "leadId", "leadName", "company", "pkg", "status",
            "kpis", "scope", "fee", "timeline", "separate_workload", "technical_route",
            "eligibility_status", "proof_status", "standard_assessment_fee", "ai_waiver_decision",
            "waiver_type", "waiver_percentage_or_amount", "waiver_reason", "waiver_scope",
            "waiver_expiry", "iwl_override_status", "iwl_override_applied", "iwl_override_reason", "final_assessment_fee",
            "final_authority", "fee_finalized_at", "customer_fee_status", "hardware_value_case",
            "hardware_target", "hardware_economics", "hardware_sponsor", "createdAt", "updatedAt",
        ]
        read_only_fields = ["id", "leadId", "createdAt", "updatedAt"]
        extra_kwargs = {
            "scope": {"required": False, "allow_blank": True},
            "fee": {"required": False, "allow_blank": True},
            "timeline": {"required": False, "allow_blank": True},
        }


class CreateEvaluationSerializer(serializers.Serializer):
    lead_id = serializers.CharField()

class AIFeeDecisionSerializer(serializers.Serializer):
    waiver_type = serializers.ChoiceField(choices=["none", "full", "partial"])
    reason = serializers.CharField()
    percentage = serializers.DecimalField(max_digits=6, decimal_places=2, required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    expiry = serializers.DateTimeField(required=False, allow_null=True)


class IWLOverrideSerializer(serializers.Serializer):
    waiver_type = serializers.ChoiceField(choices=["none", "full", "partial"])
    reason = serializers.CharField()
    final_fee = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
