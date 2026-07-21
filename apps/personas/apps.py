"""App config for the target-account persona registry."""

from __future__ import annotations

from django.apps import AppConfig


class PersonasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.personas"
    label = "personas"
    verbose_name = "Personas"
