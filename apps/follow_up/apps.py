"""AppConfig for the follow_up app."""

from __future__ import annotations

from django.apps import AppConfig


class FollowUpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.follow_up"
    label = "follow_up"
    verbose_name = "Follow-up"

    def ready(self):
        # Connect the lead-creation operations fan-out (Phase 3 wiring).
        from apps.follow_up import signals  # noqa: F401
