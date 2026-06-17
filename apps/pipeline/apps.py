"""AppConfig for the pipeline app."""

from __future__ import annotations

from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pipeline"
    label = "pipeline"
    verbose_name = "Pipeline"
