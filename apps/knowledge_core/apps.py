"""AppConfig for the knowledge_core app."""

from __future__ import annotations

from django.apps import AppConfig


class KnowledgeCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.knowledge_core"
    label = "knowledge_core"
    verbose_name = "Knowledge Core"
