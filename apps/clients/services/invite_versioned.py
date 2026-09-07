"""Transactional invite claim wrapper that binds account creation to rendered legal text."""

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
    """Claim an invite and write assent in one outer transaction.

    ``claim_invite`` remains the authoritative nonce/gate/account implementation. It is
    called with its legacy recorder disabled while this outer atomic block is open; the
    version-aware recorder then verifies the exact surface versions. A mismatch unwinds
    the nested claim savepoint, including nonce burn and Client creation.
    """

    try:
        # Validate before the claim as well, so obviously stale terms do not consume any
        # work. The recorder repeats the check before commit; the server, not the browser,
        # resolves what is currently acceptable both times.
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

    # Recovery of an already-created Client must not manufacture a duplicate assent row.
    # New claims have no row yet and are bound here before the outer transaction commits.
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

    return client, requires_password_set
