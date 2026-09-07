"""AppConfig for the evaluations app."""

from __future__ import annotations

from django.apps import AppConfig


class EvaluationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.evaluations"
    label = "evaluations"
    verbose_name = "Evaluations"

    def ready(self) -> None:
        # Import lifecycle hooks only after the app registry is ready. The hook wires
        # newly-created governed ALPHA Compute assessments to deterministic fee policy.
        from apps.evaluations import signals  # noqa: F401
