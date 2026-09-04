"""AppConfig for the leads app."""

from __future__ import annotations

from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leads"
    label = "leads"
    verbose_name = "Leads"

    def ready(self):
        # Register only synchronization signals for existing ASTOP/Evaluation records.
        # No new lifecycle is introduced; authoritative writes remain in their services.
        from apps.leads import signals_progression  # noqa: F401
