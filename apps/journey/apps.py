"""AppConfig for the journey app (progressive-disclosure state machine)."""

from __future__ import annotations

from django.apps import AppConfig


class JourneyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.journey"
    label = "journey"
    verbose_name = "Journey"
