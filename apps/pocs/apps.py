"""AppConfig for the pocs app."""

from __future__ import annotations

from django.apps import AppConfig


class PocsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pocs"
    label = "pocs"
    verbose_name = "PoCs"
