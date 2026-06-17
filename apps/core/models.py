"""
Core abstract models.

Every concrete model in the itriX backend inherits from :class:`BaseModel`, which
provides a UUID primary key and created/updated timestamps. UUID PKs matter here
because lead ids, session ids, and result-page ids are exposed in public URLs and
proxied by the frontends — sequential integer ids would leak volume and be
guessable.
"""

from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds self-managing ``created_at`` / ``updated_at`` columns."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        get_latest_by = "created_at"


class BaseModel(TimeStampedModel):
    """UUID primary key + timestamps. The base class for all itriX models."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}({self.pk})"
