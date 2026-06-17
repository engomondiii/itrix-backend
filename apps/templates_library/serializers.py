"""Template serializers — emit the dashboard's Template shape."""

from __future__ import annotations

from rest_framework import serializers

from apps.templates_library.models import Template


class TemplateSerializer(serializers.ModelSerializer):
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Template
        fields = ["id", "kind", "name", "body", "variables", "updatedAt"]
        read_only_fields = ["id", "variables", "updatedAt"]
