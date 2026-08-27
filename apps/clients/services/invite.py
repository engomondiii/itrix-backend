"""
Account-invite service.

Reveal ② mints an ``account_invite`` capability token (single-use, TTL =
ACCOUNT_INVITE_TTL_HOURS) for a lead that passed the invite gate. Reveal ③ consumes
it: ``claim_invite`` verifies the token, asserts the journey permits an invite, creates
the Client, and returns it so the view can mint a client-JWT.

Single-use enforcement: the token's nonce is consumed atomically by recording it in a
``ConsumedInvite`` row keyed by nonce. Re-claiming a consumed token fails.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.clients.models import Client
from apps.clients.services.client_creator import create_client_for_lead
from apps.journey.models import JourneyState
from apps.journey.services import capability_token as ct
from apps.journey.services.gate import account_invite_allowed

logger = logging.getLogger("itrix")


class InviteError(Exception):
    """Raised when an invite cannot be minted or claimed."""


def lookup_invite(code: str) -> tuple[bool, str]:
    """
    Is this code usable, and if so where should the visitor be sent (§15.4)?

    ── IT DOES NOT CONSUME ANYTHING ────────────────────────────────────────
    A lookup that burned the nonce would mean checking a code destroyed it. So this verifies
    the signature and expiry, checks the consumed ledger, and re-checks the journey gate —
    and leaves the token exactly as it found it. The burn happens at claim time, before
    anything can return a subject.

    ── AND IT RETURNS TWO THINGS, BECAUSE EVERYTHING IT RETURNS IS A ───────
    ── DISCLOSURE TO AN UNAUTHENTICATED PARTY ─────────────────────────────
    No Lead, no organisation, no persona, no journey state, no email, and no hint of WHICH of
    the three failure causes applied. Unknown, consumed and expired are one answer: an
    operator can tell them apart in the dashboard, and the public endpoint cannot.
    """
    token = (code or "").strip()
    if not token:
        return False, ""

    try:
        payload = ct.verify(token, expected_typ=ct.TOKEN_ACCOUNT_INVITE)
    except ct.CapabilityTokenError:
        return False, ""

    from apps.leads.models import Lead

    lead = Lead.objects.filter(id=payload.sub).first()
    if lead is None:
        return False, ""

    # Already claimed? The Client exists, so the code has done its work. Reported as
    # unusable rather than as "you already have an account" — that second answer is a fact
    # about the account.
    if Client.objects.filter(lead=lead).exists():
        return False, ""

    if payload.single_use and payload.typ == ct.TOKEN_ACCOUNT_INVITE:
        from apps.clients.models_consumed import ConsumedInvite

        if ConsumedInvite.objects.filter(nonce=payload.nonce).exists():
            return False, ""

    if not account_invite_allowed(lead):
        return False, ""

    base = (getattr(settings, "FRONTEND_WEB_URL", "") or "").rstrip("/")
    return True, f"{base}/invite/{token}/create-account" if base else f"/invite/{token}/create-account"


def mint_invite(lead) -> str:
    """Mint a single-use account_invite token for a gate-passing lead."""
    if not account_invite_allowed(lead):
        raise InviteError("Lead has not passed the account-invite gate.")
    ttl = int(getattr(settings, "ACCOUNT_INVITE_TTL_HOURS", 72)) * 3600
    return ct.mint(
        sub=str(lead.id),
        typ=ct.TOKEN_ACCOUNT_INVITE,
        state=lead.journey_state or JourneyState.INVITED,
        ttl_seconds=ttl,
        single_use=True,
    )


@transaction.atomic
def claim_invite(
    token: str,
    *,
    email: str | None = None,
    password: str | None = None,
    full_name: str = "",
    organization: str = "",
    role: str = "",
    visitor_session: str = "",
    record_assent: bool = True,
    assent_path: str = "invite_claim",
    assent_versions=None,
    assent_ip: str | None = None,
    assent_user_agent: str = "",
) -> tuple[Client, bool]:
    """
    Consume a capability token → create the Client (reveal ③).

    Accepts only the dedicated single-use ``account_invite`` token. Personalized
    My Review access no longer uses a bearer capability token in a URL, so review access
    can never be repurposed as an account-creation credential.

    Returns ``(client, requires_password_set)``. Raises ``InviteError`` on an invalid,
    expired, wrong-typed, or already-consumed token, or if the lead may not be invited.

    ── v7.1 PHASE 3: ASSENT IS RECORDED IN THIS TRANSACTION ────────────────
    "A Client never exists without the assent that created it" (Architecture v2.8 §19.10).

    Not "the view records it just afterwards" — a view that crashed between the two would
    leave an account whose basis nobody can produce, and that state cannot be repaired later
    by guessing what the person read. So the record is written HERE, inside the same atomic
    block as the nonce burn, the thread claim and the Client itself.

    ``record_assent`` defaults to True. A caller that does not want it has to say so, and the
    only legitimate reason is the RECOVERY path — a refresh or double-submit, where the Client
    already exists and already has a record. Making the safe behaviour the default means a new
    caller added later gets the gate without knowing it exists.
    """
    try:
        payload = ct.verify(token, expected_typ=ct.TOKEN_ACCOUNT_INVITE)
    except ct.CapabilityTokenError as exc:
        raise InviteError(f"Invalid invite: {exc}") from exc

    from apps.leads.models import Lead

    lead = Lead.objects.select_for_update().filter(id=payload.sub).first()
    if lead is None:
        raise InviteError("Unknown invite subject.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECURITY INVARIANT 1 — ORDER IS THE SECURITY PROPERTY
    # ─────────────────────────────────────────────────────────────────────────
    # Backend v6.0 §Phase 1: reorder to GATE -> NONCE BURN -> RECOVERY.
    #
    # The v4.0 build ran the recovery path FIRST, which meant a single-use invite token
    # could be replayed indefinitely: every replay found the existing Client and
    # returned early, before reaching the nonce burn. The token was single-use in name
    # only.
    #
    # It also let that unauthenticated recovery path SET A PASSWORD on an existing
    # account. Anyone holding a copy of the invite link could take over the workspace.
    #
    # The rule, restated: a single-use token MUST be consumed BEFORE any code path that
    # can return a subject, and NO unauthenticated claim path may set a credential on an
    # existing account.
    # ─────────────────────────────────────────────────────────────────────────

    # 1) GATE. The journey must still permit an invite when the single-use invitation
    #    is claimed. Review access and invitation access are deliberately separate.
    existing = Client.objects.filter(lead=lead).select_related("credential").first()
    if existing is None and not account_invite_allowed(lead):
        raise InviteError("This lead is no longer eligible for a workspace invite.")

    # 2) BURN. Consume the single-use nonce atomically, BEFORE anything can return a
    #    subject — including the recovery path below. A replayed token dies here.
    if payload.single_use and payload.typ == ct.TOKEN_ACCOUNT_INVITE:
        from apps.clients.models_consumed import ConsumedInvite

        try:
            ConsumedInvite.objects.create(nonce=payload.nonce, lead_id=str(lead.id))
        except IntegrityError as exc:
            raise InviteError("This invite has already been used.") from exc

    # 3) RECOVERY. Only now may we return an existing workspace. A refresh or a
    #    double-submit still logs the visitor in rather than dead-ending them at
    #    "we'll be in touch" — but a REPLAY has already been stopped at step 2.
    if existing is not None:
        _apply_recovery_details(
            existing,
            email=email,
            full_name=full_name,
            organization=organization,
            role=role,
        )
        credential = getattr(existing, "credential", None)
        requires_password_set = not (credential and credential.has_password)
        _claim_session_threads(lead, existing, visitor_session)
        return existing, requires_password_set

    client, created = create_client_for_lead(
        lead,
        email=email,
        password=password,
        full_name=full_name,
        organization=organization,
        role=role,
    )

    # ── v7.1 PHASE 3: THE ASSENT RECORD, IN THIS TRANSACTION ────────────────
    # Immediately after the Client and before anything that could return. If this raises,
    # the Client does not survive either — which is the whole point (§19.10).
    #
    # It is NOT wrapped in a try/except. Everything else in this function that is
    # best-effort says so; this one is not, because an account without a recorded basis is
    # precisely the state the rule exists to prevent and a silent failure here would be
    # indistinguishable from success.
    if record_assent:
        from apps.legal.services import assent as assent_svc

        try:
            # v7.2 — `assent_versions` is what the SURFACE rendered. The server stores its
            # OWN versions and uses these only for a mismatch check: a difference means the
            # visitor read something other than what binds them, which is worth a loud log
            # rather than a silent acceptance.
            _warn_on_version_mismatch(assent_versions)
            assent_svc.record_in_transaction(
                client=client,
                email=email or getattr(client, "email", "") or "",
                path=assent_path,
                ip_address=assent_ip,
                user_agent=assent_user_agent,
            )
        except assent_svc.AssentRefused as exc:
            # Surfaced as an InviteError so the caller's existing error handling reports it,
            # and the transaction unwinds. A workspace that could not record its own basis is
            # a workspace that must not be created.
            raise InviteError(f"Could not record legal assent: {exc}") from exc

    # Migrate the visitor's anonymous threads INSIDE this transaction, after the burn
    # (Backend v6.0 §2.2). Every turn, artifact and attachment follows them in.
    _claim_session_threads(lead, client, visitor_session)

    credential = getattr(client, "credential", None)
    requires_password_set = not (credential and credential.has_password)
    return client, requires_password_set


def _apply_recovery_details(
    client,
    *,
    email: str | None,
    full_name: str,
    organization: str,
    role: str,
) -> None:
    """
    Fill in missing profile details on an already-existing client during recovery.

    SECURITY: this function DOES NOT SET A PASSWORD, and it must never be given the
    ability to. Setting a credential here would mean an unauthenticated caller holding a
    copy of an invite link could take over an existing workspace.

    A client who needs a password gets one through the authenticated set-password flow
    (``apps.clients.services.set_password``), which proves control of the mailbox first.

    Only ever fills fields that are currently EMPTY — never clobbers existing data.
    """
    changed: list[str] = []
    if email and not client.email:
        client.email = email.strip()
        changed.append("email")
    if full_name and not client.full_name:
        client.full_name = full_name
        changed.append("full_name")
    if organization and not client.organization:
        client.organization = organization
        changed.append("organization")
    if role and not client.role:
        client.role = role
        changed.append("role")
    if changed:
        changed.append("updated_at")
        client.save(update_fields=changed)


def _claim_session_threads(lead, client, visitor_session: str) -> None:
    """
    Migrate the visitor's anonymous threads to the new Client.

    Runs inside the caller's transaction, AFTER the nonce burn. Best-effort by design:
    a visitor who never spoke has no threads, and that is normal rather than an error.
    """
    if not visitor_session:
        return
    try:
        from apps.conversations.services.claim import claim_threads

        claim_threads(visitor_session=visitor_session, client=client, lead=lead)
    except Exception:  # noqa: BLE001 - never fail a workspace creation on thread claim
        logger.exception("thread claim failed for client %s", getattr(client, "id", "?"))


def _warn_on_version_mismatch(claimed) -> None:
    """
    Log loudly when the surface rendered different instrument versions than we serve.

    Never adapts and never refuses: reconciling the two is a human decision, and refusing
    would turn a documentation drift into an outage on the account-creation path. But a
    silent mismatch means every assent recorded here is attached to a version the visitor
    did not read, so it must not pass quietly.
    """
    if not claimed:
        return
    try:
        from apps.legal.services import instruments as instruments_svc

        for entry in claimed:
            slug = (entry or {}).get("slug") if isinstance(entry, dict) else getattr(entry, "slug", None)
            version = (entry or {}).get("version") if isinstance(entry, dict) else getattr(entry, "version", None)
            if not slug or not version:
                continue
            ours = instruments_svc.version_of(slug)
            if ours and ours != version:
                logger.warning(
                    "legal.assent_version_mismatch slug=%s surface=%s server=%s "
                    "(the visitor read a different version than the one being recorded)",
                    slug,
                    version,
                    ours,
                )
    except Exception:  # noqa: BLE001 - a mismatch CHECK must never break a claim
        logger.debug("assent version mismatch check skipped")
