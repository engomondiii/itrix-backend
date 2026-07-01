"""AppConfig for the clients app (the client identity plane)."""

from __future__ import annotations

from django.apps import AppConfig


class ClientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clients"
    label = "clients"
    verbose_name = "Clients"
