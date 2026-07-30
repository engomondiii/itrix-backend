"""
EMAIL VERIFICATION TOKENS (Backend v7.2 §15.2).

Same shape and the same reasoning as ``PasswordResetToken``: hashed at rest, single-use,
short-lived, and `invalidated_at` separate from `consumed_at`.

── THE ADDRESS BEING PROVEN IS STORED ON THE TOKEN ─────────────────────────
Not read from the Client at confirm time. If the Client's email changes between the send
and the click, confirming the OLD link must not verify the NEW address — otherwise a
person could point their account at somebody else's mailbox and then confirm it with a
link that was issued for their own.
"""

from __future__ import annotations

import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class EmailVerificationToken(BaseModel):
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="verification_tokens"
    )
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Email verification token"
        verbose_name_plural = "Email verification tokens"
        indexes = [models.Index(fields=["client", "consumed_at"])]

    def __str__(self) -> str:
        return f"EmailVerificationToken({self.client_id})"

    @property
    def is_usable(self) -> bool:
        return (
            self.consumed_at is None
            and self.invalidated_at is None
            and self.expires_at > timezone.now()
        )
