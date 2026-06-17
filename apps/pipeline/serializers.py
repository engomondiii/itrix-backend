"""
Pipeline serializers.

The board reuses the leads list-item shape for each card, adding an ``overdue`` flag that the
dashboard renders as an error bar. A stage is one ``LeadStatus`` with its cards + count, and
the board is the ordered list of stages (pipeline column order matches the dashboard).
"""

from __future__ import annotations

from rest_framework import serializers

from apps.leads.serializers import LeadListSerializer


class PipelineCardSerializer(LeadListSerializer):
    overdue = serializers.SerializerMethodField()

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + ["overdue"]

    def get_overdue(self, obj) -> bool:
        return bool(self.context.get("overdue_lead_ids", set()) and str(obj.id) in self.context["overdue_lead_ids"])
