"""AppConfig for the nda app."""

from __future__ import annotations

from django.apps import AppConfig


class NdaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.nda"
    label = "nda"
    verbose_name = "NDA"
