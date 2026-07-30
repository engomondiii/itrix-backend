"""
OPEN REGISTRATION (Architecture v2.9 §27.4, Backend v7.2 §15.5, R60–R64).

── WHY THIS IS SAFE, IN ONE EXPRESSION ─────────────────────────────────────
    effective_ceiling = min(plane_cap, STATE_CEILING[journey_number(state)])

`STATE_CEILING[1]` is `public`. A Client created here sits at `ARRIVED`, so it reaches
exactly what an anonymous visitor reaches. An account is not an input to that expression,
and `tests/test_journey/test_account_does_not_raise_ceiling.py` asserts it at every state
so it stays that way (R59).

── THREE THINGS THE CODE FORCED THAT THE FIRST DRAFT OF THE SPEC DID NOT ───
1. `Client.lead` is a NON-NULL OneToOneField, so "lead = None" was never implementable.
   Registration MINTS a Lead at `ARRIVED` with `lead_source = self_serve`, which keeps
   every existing reader of journey state on one code path.
2. `create_client_for_lead()` calls `accept_invite(lead)`, and `ACCEPT_INVITE` is legal
   only from `INVITED`. Reusing it unchanged would log a failed advance on every signup —
   and if the transition table were ever loosened, would put a silent account at State 6
   with an `nda_only` ceiling. Hence `advance_journey=False` (R61).
3. Assent cannot be recorded by a prior request: `portal/legal/assent/` authenticates on
   the client plane, and before this function runs there is neither a client-JWT nor a
   Client. The versions arrive in the payload and are written HERE (R62).

── ONE CREATOR, NOT TWO ────────────────────────────────────────────────────
This orchestrates; it does not duplicate. `create_client_for_lead()` remains the only
function that instantiates a Client and a ClientCredential, because a second one would be
a second place for the credential invariants and the portal bootstrap to drift — and the
drift would be invisible until a customer could not log in (§11.7).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction

from apps.clients.models import AccountOrigin, Client
from apps.clients.models_reset import new_token

logger = logging.getLogger("itrix")


class RegistrationError(Exception):
    """A refusal the caller may report. NEVER used for "this address is taken"."""


class RegistrationOutcome:
    """
    Accepted, and deliberately vague about whether anything was created.

    The view answers 202 with one body either way (R64), so the only thing a caller needs
    is "the request was handled". `created` exists for tests and logging and must never
    reach a response.
    """

    def __init__(self, *, created: bool, client=None):
        self.created = created
        self.client = client


def enabled() -> bool:
    return bool(getattr(settings, "ENABLE_OPEN_SIGNUP", True))


@transaction.atomic
def register_client(
    *,
    email: str,
    password: str,
    full_name: str,
    organization: str,
    role: str = "",
    assent_versions=None,
    accepted_at_client=None,
    visitor_session: str = "",
    ip: str | None = None,
    user_agent: str = "",
) -> RegistrationOutcome:
    """Create a workspace for anyone. See the module docstring for why that is safe."""
    from apps.clients.services.client_creator import create_client_for_lead
    from apps.clients.services.verification import mint as mint_verification
    from apps.clients.services.verification import send as send_verification
    from apps.journey.models import JourneyState
    from apps.leads.models import Lead, LeadSource, LeadStatus
    from apps.legal.models import AssentRecord
    from apps.legal.services import assent as assent_svc

    address = (email or "").strip()
    if not address or not password:
        raise RegistrationError("An email address and a password are required.")

    # ── 1. ONE ADDRESS, ONE ACCOUNT (R63) ────────────────────────────────────
    # Checked here AND constrained in the database. The constraint is what makes
    # `authenticate_client()`'s `.first()` deterministic; this check is what lets us notify
    # the holder instead of raising an integrity error at the caller.
    existing = Client.objects.filter(email__iexact=address, is_active=True).first()
    if existing is not None:
        _notify_existing_holder(existing)
        # A dummy hash so the two branches cost comparable time. The response is already
        # identical; timing is the same oracle, more quietly.
        make_password(new_token())
        logger.info("clients.registration_address_in_use")
        return RegistrationOutcome(created=False)

    # ── 2. THE LEAD. `Client.lead` is NOT NULL, so there is always one ───────
    lead = Lead.objects.create(
        email=address,
        visitor_name=(full_name or "").strip(),
        company=(organization or "").strip(),
        role=(role or "").strip(),
        journey_state=JourneyState.ARRIVED,
        lead_source=LeadSource.SELF_SERVE,
        status=LeadStatus.NEW,
    )

    # ── 3. THE CLIENT — one creator, with the journey advance switched off ───
    client, _created = create_client_for_lead(
        lead,
        email=address,
        password=password,
        full_name=(full_name or "").strip(),
        organization=(organization or "").strip(),
        role=(role or "").strip(),
        advance_journey=False,
    )
    client.account_origin = AccountOrigin.SELF_SERVE
    client.save(update_fields=["account_origin", "updated_at"])

    # ── 4. ASSENT, IN THIS TRANSACTION. NOT wrapped in try/except ───────────
    # Everything else in this function that is best-effort says so. This is not: an account
    # without a recorded basis is precisely the state §19.10 exists to prevent, and a silent
    # failure here would be indistinguishable from success.
    assent_svc.record_in_transaction(
        client=client,
        email=address,
        path=AssentRecord.Path.OPEN_REGISTRATION,
        accepted_at_client=accepted_at_client,
        ip_address=ip,
        user_agent=user_agent,
    )

    # ── 5. THE VISITOR'S ANONYMOUS THREADS FOLLOW THEM IN (R65) ─────────────
    _claim_session_threads(lead, client, visitor_session)

    # ── 6. THE VERIFICATION TOKEN, INSIDE THE TRANSACTION ───────────────────
    token = mint_verification(client, address, ip=ip)
    transaction.on_commit(lambda: send_verification(client, token))

    logger.info("clients.registered client=%s lead=%s", client.id, lead.id)
    return RegistrationOutcome(created=True, client=client)


def _notify_existing_holder(client) -> None:
    """
    Tell the PERSON WHO OWNS the address, never the person who typed it (§27.6).

    This costs real usability — somebody who forgot they had an account gets a confirmation
    screen and then a security-flavoured email. We take the cost, because the alternative is
    a public endpoint that answers "is this company your customer?" for anyone who can type
    an address (R57).
    """
    try:
        from apps.emails.services.address_in_use_builder import build_address_in_use_email

        build_address_in_use_email(client)
    except Exception:  # noqa: BLE001 - a failed notice must not become a signal
        logger.exception("address-in-use notice failed for client %s", getattr(client, "id", "?"))


def _claim_session_threads(lead, client, visitor_session: str) -> None:
    """
    Migrate the visitor's anonymous threads. The same call the invite path makes, with the
    same privacy boundaries: never across sessions, never linking two anonymous sessions.

    Best-effort by design — somebody who registered before saying anything has no threads,
    and that is normal rather than an error.
    """
    if not visitor_session:
        return
    try:
        from apps.conversations.services.claim import claim_threads

        claim_threads(visitor_session=visitor_session, client=client, lead=lead)
    except Exception:  # noqa: BLE001
        logger.exception("thread claim failed for client %s", getattr(client, "id", "?"))
