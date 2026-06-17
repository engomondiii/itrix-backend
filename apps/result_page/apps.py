"""AppConfig for the result_page app."""

from __future__ import annotations

from django.apps import AppConfig


class ResultPageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.result_page"
    label = "result_page"
    verbose_name = "Result Page"
