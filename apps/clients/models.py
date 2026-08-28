"""
Client identity models (Backend v4 §3.1, the client plane).

A ``Client`` is an account-holding subject created when a Lead accepts a workspace
invite (reveal ③). It is the anchor of the client-JWT plane (audience=client), whose baseline disclosure ceiling remains controlled-public. NDA/agreement state can be a prerequisite for a separately authorized disclosure, but never raises access by itself. The Client is linked 1:1 back to its Lead
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
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import BaseModel


class AccountOrigin(models.TextChoices):
    """
    How this ACCOUNT was opened (v7.2, Architecture v2.9 §15.7).

    Two provenance fields rather than one: `Lead.lead_source` says how the SUBJECT entered
    the system, this says how the ACCOUNT was opened. A self-serve account that later
    receives a proper invitation for a second engagement keeps `self_serve`, and that is
    correct — the account was not earned, and the record should not be rewritten to say it
    was.

    INTERNAL-ONLY. It is a fact about how we acquired somebody, which puts it on the §10.5
    list beside persona, tier and score.
    """

    INVITED = "invited", "Invited"
    SELF_SERVE = "self_serve", "Self-serve registration"


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
    # Self-asserted identity/profile claims. They remain claims until an operator or
    # approved external verification workflow records verification timestamps below.
    # Neither a claim nor verification expands disclosure without ContentAuthorization.
    claimed_identity = models.JSONField(default=dict, blank=True)
    identity_verified_at = models.DateTimeField(null=True, blank=True, db_index=True)
    organization_verified_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # NDA state records agreement protection only. It never creates content authorization.
    nda_signed = models.BooleanField(default=False)
    nda_signed_at = models.DateTimeField(null=True, blank=True)
    # When the customer asked for an NDA from the Documents screen (2026-08-10).
    # Distinct from nda_signed_at, which records the countersigned fact: a request
    # is a request, and conflating the two would show a data room as open because
    # somebody pressed a button.
    nda_requested_at = models.DateTimeField(null=True, blank=True)

    # Portal settings (§68): the client's notification switches. A plain JSON map so
    # adding a switch is a copy change, not a migration; absent keys fall back to the
    # defaults in views (everything on), so an empty dict means "never touched".
    notification_prefs = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # ── v7.2: open registration, confirmation, and session invalidation ──────
    account_origin = models.CharField(
        max_length=16,
        choices=AccountOrigin.choices,
        default=AccountOrigin.INVITED,
        db_index=True,
    )
    # NULL means the address has not been confirmed. Confirmation gates three things and
    # only three: any non-transactional email, putting an NDA in place, and being named on
    # a commercial document (Architecture v2.9 R66). It does NOT gate signing in, posting a
    # turn, or receiving an answer.
    email_verified_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Stamped on every password change. A client-JWT minted BEFORE this moment is refused,
    # which is how a stateless token gets invalidated (services/session_invalidation.py).
    password_changed_at = models.DateTimeField(null=True, blank=True)

    # ── v6.0 Phase 2: the customer lifecycle ─────────────────────────────────
    # A Client becomes a CUSTOMER when a contract is executed. The distinction matters
    # because it can satisfy an agreement prerequisite for customer-contract material.
    # It is never sufficient disclosure authorization: a specific ContentAuthorization is still required.
    contract_state = models.CharField(
        max_length=24,
        blank=True,
        default="",
        db_index=True,
        help_text="'' | negotiating | executed | active | churned",
    )
    # R16: customer-success modules activate at the FIRST PAYMENT, not at license-out.
    # A paid Assessment customer already has named owners, support and success goals.
    first_payment_recorded_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Derived health class. INTERNAL-ONLY (§10.5) — never on a client-plane payload.
    # NULL means UNKNOWN, and unknown must never authorize an expansion (see
    # journey.services.gate.expansion_allowed).
    customer_health = models.CharField(
        max_length=16,
        blank=True,
        default="",
        db_index=True,
        help_text="'' (unknown) | stable | at_risk | critical",
    )

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            # ── ONE ADDRESS, ONE ACCOUNT (v7.2 §15.9, R63) ──────────────────
            # Enforced in the DATABASE rather than checked in a view, because
            # `authenticate_client()` resolves a login with
            # `filter(email__iexact=...).first()`. Two rows sharing an address made which
            # one you signed into arbitrary; with the constraint there is only ever one row
            # to pick, and that `.first()` becomes deterministic.
            #
            # Lower(): the lookup is case-insensitive, and a constraint that disagreed with
            # the lookup would not be a constraint.
            # is_active: closing an account must not permanently burn an address.
            # non-empty: the column permits '' (no blank=True is a FORM rule, not a database
            #            one) and several legacy rows may hold it, so a plain unique index
            #            would refuse the second one.
            models.UniqueConstraint(
                Lower("email"),
                condition=Q(is_active=True) & ~Q(email=""),
                name="uniq_active_client_email_ci",
            ),
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

# v7.2 — the two single-use credential tokens. Imported here for the same reason: a model in
# a module nobody imports is a model Django never registers, and the migration that creates
# its table would then never be generated.
from apps.clients.models_reset import PasswordResetToken  # noqa: E402,F401
from apps.clients.models_verification import EmailVerificationToken  # noqa: E402,F401


class ClientTeamInvite(BaseModel):
    """
    A teammate the client asked to bring into their workspace (§68 team access).

    DELIBERATELY MINIMAL. The row is the durable record that the invitation was
    made — it is what the Settings screen lists as 'invited'. It does not yet
    grant the invitee an account: activation (the invitee setting a password and
    the two accounts sharing the workspace) is a later, deliberate step, and
    pretending otherwise here would show 'active' teammates who cannot sign in.
    """

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        REVOKED = "revoked", "Revoked"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="team_invites"
    )
    email = models.EmailField(db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.INVITED, db_index=True
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["client", "email"], name="uniq_invite_per_client_email"),
        ]

    def __str__(self) -> str:
        return f"ClientTeamInvite({self.email}, {self.status})"
