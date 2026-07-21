"""App config for the State 10 customer-success domain."""

from __future__ import annotations

from django.apps import AppConfig


class CustomerSuccessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.customer_success"
    label = "customer_success"
    verbose_name = "Customer success"
