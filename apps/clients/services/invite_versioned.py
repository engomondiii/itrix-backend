"""Transactional invite claim wrapper binding account creation to legal text and history."""

from __future__ import annotations

from django.db import transaction

from apps.clients.services.invite import InviteError, claim_invite
from apps.legal.services import assent as assent_svc


class InviteLegalTermsChanged(InviteError):
    code = "LEGAL_TERMS_CHANGED"


@transaction.atomic
def claim_invite_with_version_integrity(
    token: str,
    *,
    email: str | None = None,
    password: str | None = None,
    full_name: str = "",
    organization: str = "",
    role: str = "",
    visitor_session: str = "",
    assent_versions=None,
    assent_path: str = "invite_claim",
    assent_ip: str | None = None,
    assent_user_agent: str = "",
):
    """Claim invite + assent + anonymous history in one outer transaction."""

    try:
        assent_svc.require_current_rendered_versions(assent_versions)
    except assent_svc.LegalTermsChanged as exc:
        raise InviteLegalTermsChanged(str(exc)) from exc

    client, requires_password_set = claim_invite(
        token,
        email=email,
        password=password,
        full_name=full_name,
        organization=organization,
        role=role,
        visitor_session=visitor_session,
        record_assent=False,
        assent_path=assent_path,
        assent_versions=assent_versions,
        assent_ip=assent_ip,
        assent_user_agent=assent_user_agent,
    )

    if not client.assent_records.exists():
        try:
            assent_svc.record_in_transaction(
                client=client,
                email=email or getattr(client, "email", "") or "",
                path=assent_path,
                rendered_versions=assent_versions,
                ip_address=assent_ip,
                user_agent=assent_user_agent,
            )
        except assent_svc.LegalTermsChanged as exc:
            raise InviteLegalTermsChanged(str(exc)) from exc
        except assent_svc.AssentRefused as exc:
            raise InviteError(f"Could not record legal assent: {exc}") from exc

    # ``claim_invite`` historically invokes a best-effort helper. Repeat the operation at
    # this transaction boundary as a load-bearing, idempotent assertion. If the first call
    # already succeeded there are no session-owned rows left; if it failed, this call must
    # succeed or the outer transaction rolls back nonce burn, Client, and assent together.
    if visitor_session:
        from apps.conversations.services.claim import claim_threads

        claim_threads(visitor_session=visitor_session, client=client, lead=client.lead)

    return client, requires_password_set
