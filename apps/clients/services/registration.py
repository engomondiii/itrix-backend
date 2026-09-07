"""
OPEN REGISTRATION (Architecture v2.9 §27.4, Backend v7.2 §15.5, R60–R64).

Open registration mints a neutral State-1 Lead/Client. Legal assent and account creation
share one transaction, and the versions reported by the surface are verified against the
running deployment before any address-dependent branch executes. A legal-version race is
therefore safe and cannot become an account-enumeration signal.
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


class RegistrationLegalTermsChanged(RegistrationError):
    """Rendered legal versions are no longer current; safe to expose for every address."""

    code = "LEGAL_TERMS_CHANGED"


class RegistrationOutcome:
    """Accepted, deliberately vague about whether anything was created."""

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
    """Create a neutral workspace while preserving account and assent invariants."""
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

    # Legal currentness is checked BEFORE the address lookup so stale terms produce the
    # same response for a new and an existing address. This preserves R64 while ensuring
    # nobody can be recorded against a version they did not render.
    try:
        assent_svc.require_current_rendered_versions(assent_versions)
    except assent_svc.LegalTermsChanged as exc:
        raise RegistrationLegalTermsChanged(str(exc)) from exc
    except assent_svc.AssentRefused:
        # Missing/misconfigured server legal evidence is an operational hard failure, not
        # an ordinary registration refusal. Let the view's generic 503 path report it
        # safely; collapsing it into 202 would falsely imply the request was accepted.
        raise

    # ── 1. ONE ADDRESS, ONE ACCOUNT (R63) ────────────────────────────────────
    existing = Client.objects.filter(email__iexact=address, is_active=True).first()
    if existing is not None:
        _notify_existing_holder(existing)
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

    # ── 3. THE CLIENT — one creator, with journey advance switched off ───────
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

    # ── 4. ASSENT, IN THIS TRANSACTION ───────────────────────────────────────
    try:
        assent_svc.record_in_transaction(
            client=client,
            email=address,
            path=AssentRecord.Path.OPEN_REGISTRATION,
            rendered_versions=assent_versions,
            accepted_at_client=accepted_at_client,
            ip_address=ip,
            user_agent=user_agent,
        )
    except assent_svc.LegalTermsChanged as exc:
        raise RegistrationLegalTermsChanged(str(exc)) from exc
    except assent_svc.AssentRefused:
        # Same invariant as the pre-check: account creation must fail with the recorder.
        raise

    # ── 5. THE VISITOR'S ANONYMOUS THREADS FOLLOW THEM IN (R65) ─────────────
    _claim_session_threads(lead, client, visitor_session)

    # ── 6. THE VERIFICATION TOKEN, INSIDE THE TRANSACTION ───────────────────
    token = mint_verification(client, address, ip=ip)
    transaction.on_commit(lambda: send_verification(client, token))

    logger.info("clients.registered client=%s lead=%s", client.id, lead.id)
    return RegistrationOutcome(created=True, client=client)


def _notify_existing_holder(client) -> None:
    """Notify the holder, not the unauthenticated requester, when an address is in use."""
    try:
        from apps.emails.services.address_in_use_builder import build_address_in_use_email

        build_address_in_use_email(client)
    except Exception:  # noqa: BLE001 - a failed notice must not become a signal
        logger.exception("address-in-use notice failed for client %s", getattr(client, "id", "?"))


def _claim_session_threads(lead, client, visitor_session: str) -> None:
    """Migrate this visitor session's anonymous threads to the new account."""
    if not visitor_session:
        return
    try:
        from apps.conversations.services.claim import claim_threads

        claim_threads(visitor_session=visitor_session, client=client, lead=lead)
    except Exception:  # noqa: BLE001
        logger.exception("thread claim failed for client %s", getattr(client, "id", "?"))
