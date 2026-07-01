"""
Client identity models (Backend v4 §3.1, the client plane).

A ``Client`` is an account-holding subject created when a Lead accepts a workspace
invite (reveal ③). It is the anchor of the client-JWT plane (audience=client), whose
disclosure ceiling is NDA-gated (≤ NDA_ONLY). The Client is linked 1:1 back to its Lead
so the journey state mirrors across.

``ClientCredential`` stores the client's password hash (separate from the team User
model — clients are NOT Django auth users; they authenticate on their own plane via
``ClientJWTAuth``). This keeps the two identity planes cleanly separated.

Phase 1 ships this as scaffolding: the models + auth backend + token minting + creator
+ invite service exist and are unit-tested, and the invite-claim endpoint is live. The
portal endpoints that consume the client-JWT arrive in Phase 2.
"""

from __future__ import annotations

from django.contrib.auth.hashers import check_password, make_password
from django.db import models

from apps.core.models import BaseModel


class Client(BaseModel):
    """An account-holding client (the client identity plane subject)."""

    # 1:1 back to the originating lead. The lead is authoritative for journey state.
    lead = models.OneToOneField(
        "leads.Lead",
        on_delete=models.CASCADE,
        related_name="client_account",
    )

    email = models.EmailField(db_index=True)
    full_name = models.CharField(max_length=200, blank=True, default="")
    organization = models.CharField(max_length=200, blank=True, default="")
    role = models.CharField(max_length=120, blank=True, default="")

    # NDA state gates the client's disclosure ceiling and the data room (reveal ④).
    nda_signed = models.BooleanField(default=False)
    nda_signed_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"Client({self.email or self.full_name or self.id})"

    @property
    def display_name(self) -> str:
        return self.full_name or self.email

    # ── DRF/Django compatibility (client plane) ──────────────────────────────
    # A Client is the authenticated "user" on the client-JWT plane. DRF throttling and
    # other middleware treat request.user like a Django user, so we expose the same
    # duck-typed flags. A Client is never a Django auth user (no permissions, no session).
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False


class ClientCredential(BaseModel):
    """
    A client's password credential. Separate from the team ``User`` model — the two
    identity planes never share credentials. Uses Django's password hashers.
    """

    client = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name="credential",
    )
    password_hash = models.CharField(max_length=256, blank=True, default="")
    # Single-use token for first-time password set / reset (opaque, hashed value).
    set_password_token = models.CharField(max_length=128, blank=True, default="", db_index=True)
    set_password_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Client credential"
        verbose_name_plural = "Client credentials"

    def __str__(self) -> str:
        return f"ClientCredential({self.client_id})"

    def set_password(self, raw_password: str) -> None:
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password(raw_password, self.password_hash)

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)


# Import the single-use invite ledger so it is registered with this app's models.
from apps.clients.models_consumed import ConsumedInvite  # noqa: E402,F401
