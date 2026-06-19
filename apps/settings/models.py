"""
Operator settings models.

Two small pieces of dashboard configuration that the front-end's settings screens
read and write (``itrix-dashboard/src/types/settings.ts``):

* :class:`SlaThresholds` — an org-wide singleton holding the per-tier response SLA
  in hours. The dashboard serializes it as ``{ "1": n, "2": n, "3": n, "4": n }``
  (``SlaConfig = Record<Tier, number | null>``); ``null`` means "no human SLA".
* :class:`NotificationPreference` — per-user toggles
  (``{ tier1, sla, nda, weekly }``) for which alerts an operator wants.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class SlaThresholds(BaseModel):
    """Org-wide SLA response thresholds (hours) per lead tier. Singleton row.

    Defaults mirror the dashboard's ``TIER_DEFS`` (24h / 48h / 24h / none).
    """

    tier1_hours = models.PositiveIntegerField(null=True, blank=True, default=24)
    tier2_hours = models.PositiveIntegerField(null=True, blank=True, default=48)
    tier3_hours = models.PositiveIntegerField(null=True, blank=True, default=24)
    tier4_hours = models.PositiveIntegerField(null=True, blank=True, default=None)

    class Meta:
        verbose_name = "SLA thresholds"
        verbose_name_plural = "SLA thresholds"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"SLA thresholds (T1={self.tier1_hours}h, T2={self.tier2_hours}h)"

    @classmethod
    def load(cls) -> "SlaThresholds":
        """Return the singleton row, creating it with defaults on first access."""
        obj = cls.objects.order_by("created_at").first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class NotificationPreference(BaseModel):
    """Per-operator notification toggles."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )
    # New Tier 1 lead arrives.
    tier1 = models.BooleanField(default=True)
    # A follow-up breaches its SLA.
    sla = models.BooleanField(default=True)
    # An NDA is signed.
    nda = models.BooleanField(default=False)
    # Weekly pipeline report digest.
    weekly = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Notification preference"
        verbose_name_plural = "Notification preferences"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Notification prefs for {self.user_id}"

    @classmethod
    def for_user(cls, user) -> "NotificationPreference":
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
