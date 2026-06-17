"""AppConfig for the ai_engine app."""

from __future__ import annotations

from django.apps import AppConfig


class AiEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_engine"
    label = "ai_engine"
    verbose_name = "AI Engine"
