"""
PASSWORD RESET TOKENS (Backend v7.2 §15.2).

── THE TOKEN IS STORED HASHED, AND ONLY HASHED ─────────────────────────────
A reset token is a bearer credential for an account. A database dump containing usable
ones is an account-takeover list, so only a hash is stored and the plaintext exists
exactly once — in the email.

sha256 rather than a password hasher, deliberately: the token is 32 bytes of
`secrets.token_urlsafe` entropy, so there is nothing to brute-force and a slow hash would
only add latency to a lookup that runs on an unauthenticated endpoint.

── `invalidated_at` IS SEPARATE FROM `consumed_at` ON PURPOSE ──────────────
Requesting a new link invalidates the previous one WITHOUT consuming it, and in an
incident the two states answer different questions: *was this used?* versus *was it
superseded?* One nullable column each is cheaper than reconstructing that from timestamps
later.
"""

from __future__ import annotations

import hashlib
import secrets

from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel


def new_token() -> str:
    """A fresh plaintext token. Never stored — only its hash is."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class PasswordResetToken(BaseModel):
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="reset_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Password reset token"
        verbose_name_plural = "Password reset tokens"
        indexes = [models.Index(fields=["client", "consumed_at"])]

    def __str__(self) -> str:
        return f"PasswordResetToken({self.client_id})"

    @property
    def is_usable(self) -> bool:
        return (
            self.consumed_at is None
            and self.invalidated_at is None
            and self.expires_at > timezone.now()
        )
