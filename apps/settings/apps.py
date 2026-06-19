"""App config for the operator settings app (SLA thresholds + notification prefs)."""

from __future__ import annotations

from django.apps import AppConfig


class SettingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.settings"
    label = "itrix_settings"
    verbose_name = "Operator settings"
