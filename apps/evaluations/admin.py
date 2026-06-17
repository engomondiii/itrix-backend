"""Admin for evaluations."""

from __future__ import annotations

from django.contrib import admin

from apps.evaluations.models import Evaluation


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ("id", "lead_name", "pkg", "status", "created_at", "updated_at")
    list_filter = ("status", "pkg")
    search_fields = ("lead_name", "company")
