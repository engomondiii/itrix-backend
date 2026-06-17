"""Reporting serializers — emit the dashboard's MonthlyReport shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.reporting.models import MonthlyReport


class MonthlyReportSerializer(serializers.ModelSerializer):
    generatedAt = serializers.DateTimeField(source="generated_at", read_only=True)

    class Meta:
        model = MonthlyReport
        fields = ["id", "month", "generatedAt", "sections"]
        read_only_fields = fields


class GenerateReportSerializer(serializers.Serializer):
    month = serializers.CharField(required=False, allow_blank=True, default="")
