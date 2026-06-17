"""AppConfig for the emails app."""

from __future__ import annotations

from django.apps import AppConfig


class EmailsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.emails"
    label = "emails"
    verbose_name = "Emails"
