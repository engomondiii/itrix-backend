"""AppConfig for the routing app."""

from __future__ import annotations

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.routing"
    label = "routing"
    verbose_name = "Routing"
