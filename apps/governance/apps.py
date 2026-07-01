"""AppConfig for the governance app (the Claim-Card fabric)."""

from __future__ import annotations

from django.apps import AppConfig


class GovernanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.governance"
    label = "governance"
    verbose_name = "Governance"
