"""
Single-use invite ledger.

``ConsumedInvite`` records the nonce of each account_invite token the moment it is
claimed. The nonce column is unique, so a concurrent or repeated claim of the same
token raises IntegrityError — that is how single-use is enforced atomically inside the
claim transaction (see services/invite.py).
"""

from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel


class ConsumedInvite(BaseModel):
    nonce = models.CharField(max_length=64, unique=True, db_index=True)
    lead_id = models.CharField(max_length=64, db_index=True)

    class Meta:
        verbose_name = "Consumed invite"
        verbose_name_plural = "Consumed invites"

    def __str__(self) -> str:
        return f"ConsumedInvite({self.nonce[:8]}… lead={self.lead_id})"
