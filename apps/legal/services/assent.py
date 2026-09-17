"""
RECORDING ASSENT (Architecture v2.8 §19.10, R44).

Every client-creating path writes assent inside the same database transaction as the
Client. When a surface supplies the instrument versions it rendered, those versions are
also verified against the running deployment inside that transaction. A deployment/version
race therefore rolls the account creation back instead of recording evidence for text the
visitor never saw.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.legal.constants import ASSENT_REQUIRED_SLUGS
from apps.legal.services import instruments as instruments_svc

logger = logging.getLogger("itrix")


class AssentRefused(Exception):
    """Raised when assent cannot be recorded. Never swallowed by a caller."""


class LegalTermsChanged(AssentRefused):
    """The versions rendered to the visitor are no longer the acceptable versions."""

    code = "LEGAL_TERMS_CHANGED"


def _require_open_transaction() -> None:
    from django.db import connection

    if not connection.in_atomic_block:
        raise AssentRefused(
            "record_in_transaction must be called inside an atomic block, so the assent "
            "record and the Client land together or not at all "
            "(Architecture v2.8 §19.10). Wrap the caller in transaction.atomic()."
        )


def _field(entry, key: str) -> str:
    if isinstance(entry, dict):
        value = entry.get(key)
    else:
        value = getattr(entry, key, None)
    return str(value or "").strip()


def require_current_rendered_versions(rendered_versions, slugs=None) -> list[dict]:
    """Verify that the exact rendered legal versions are still the server-current set.

    The browser does not get to choose which legal version is valid. It only reports what
    it rendered; this function resolves the legitimate current instruments server-side and
    requires an exact match for every assent-bearing slug. Effective date is checked too,
    so a publication-state or document replacement cannot hide behind a reused version
    label. Unknown/duplicate/missing rendered entries fail closed.
    """

    required = list(slugs or ASSENT_REQUIRED_SLUGS)
    try:
        current = instruments_svc.current_versions(required)
    except ValueError as exc:
        raise AssentRefused(str(exc)) from exc

    claimed_by_slug: dict[str, object] = {}
    for entry in list(rendered_versions or []):
        slug = _field(entry, "slug")
        if not slug:
            continue
        if slug in claimed_by_slug:
            raise LegalTermsChanged("The legal terms changed while they were being reviewed.")
        claimed_by_slug[slug] = entry

    expected_by_slug = {entry["slug"]: entry for entry in current}
    for slug in required:
        rendered = claimed_by_slug.get(slug)
        expected = expected_by_slug[slug]
        if rendered is None:
            raise LegalTermsChanged("The legal terms changed while they were being reviewed.")
        if _field(rendered, "version") != str(expected.get("version") or ""):
            raise LegalTermsChanged("The legal terms changed while they were being reviewed.")
        if _field(rendered, "effective") != str(expected.get("effective") or ""):
            raise LegalTermsChanged("The legal terms changed while they were being reviewed.")

    return current


def record_in_transaction(
    *,
    client=None,
    email: str = "",
    path: str,
    slugs=None,
    rendered_versions=None,
    accepted_at_client=None,
    ip_address: str | None = None,
    user_agent: str = "",
):
    """Write the assent record inside the caller's account-creation transaction.

    When ``rendered_versions`` is supplied, account creation is additionally bound to the
    exact versions the visitor saw. The server resolves the acceptable versions itself and
    never trusts an arbitrary client version string as evidence.
    """
    from apps.legal.models import AssentRecord

    _require_open_transaction()
    required = list(slugs or ASSENT_REQUIRED_SLUGS)

    if rendered_versions is not None:
        entries = require_current_rendered_versions(rendered_versions, required)
    else:
        # Retained for internal/legacy callers that do not render an instrument surface.
        # New visitor-facing account-creation paths must provide rendered_versions.
        try:
            entries = instruments_svc.current_versions(required)
        except ValueError as exc:
            raise AssentRefused(str(exc)) from exc

    resolved_email = (email or getattr(client, "email", "") or "").strip()
    if not resolved_email and client is None:
        raise AssentRefused(
            "An assent record needs either a Client or an email address; otherwise it "
            "attests to nothing identifiable."
        )

    status_value = (
        "published_assent" if instruments_svc.published() else "draft_acknowledgement"
    )
    record = AssentRecord.objects.create(
        client=client,
        client_email_at_assent=resolved_email,
        instruments=entries,
        instrument_status=status_value,
        path=path,
        accepted_at_client=accepted_at_client,
        ip_address=ip_address or None,
        user_agent=(user_agent or "")[:300],
    )
    logger.info(
        "legal.assent_recorded path=%s client=%s status=%s versions=%s",
        path,
        getattr(client, "id", None),
        status_value,
        {e["slug"]: e["version"] for e in entries},
    )
    return record


def latest_for(client):
    """The most recent assent record for ``client``, or None."""
    from apps.legal.models import AssentRecord

    if client is None:
        return None
    return AssentRecord.objects.filter(client=client).order_by("-created_at").first()


def has_current_assent(client) -> bool:
    """Whether ``client`` has accepted the versions currently in force."""
    record = latest_for(client)
    if record is None:
        return False
    expected_status = (
        "published_assent" if instruments_svc.published() else "draft_acknowledgement"
    )
    if record.instrument_status != expected_status:
        return False
    for slug in ASSENT_REQUIRED_SLUGS:
        current = instruments_svc.display_version_of(slug)
        if not current or record.version_of(slug) != current:
            return False
    return True


def clients_without_assent():
    """Every active Client with no assent record. SHOULD ALWAYS BE EMPTY."""
    from apps.clients.models import Client

    return Client.objects.filter(is_active=True, assent_records__isnull=True)
