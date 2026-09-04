"""
RECORDING ASSENT (Architecture v2.8 §19.10, R44).

── ONE RECORDER, CALLED BY EVERY CLIENT-CREATING PATH ──────────────────────

There are three doors to an account: the emailed capability link, an invite code entered
from a cold start, and — behind a flag — open registration. All three call
``record_in_transaction``, and ``tests/test_legal/test_no_client_without_assent.py``
asserts the invariant across all three rather than trusting each view.

That matters because a fourth door added later fails the test instead of quietly skipping
the gate. A per-view habit would not do that; it would just be a habit.

── IN THE SAME TRANSACTION AS THE CLIENT ───────────────────────────────────
"A Client never exists without the assent that created it." Not "usually", and not "the
view records it right afterwards" — a view that crashed between the two would leave an
account whose basis nobody can produce, and that state cannot be repaired later by guessing
what the person read.

So ``record_in_transaction`` requires an open atomic block and says so if there is not one.
A silent success outside a transaction is the failure this whole module exists to prevent.

── WHAT IT REFUSES TO RECORD ───────────────────────────────────────────────
An unknown instrument slug, or an instrument with no configured version. Both produce
evidence that looks like evidence and proves nothing — you cannot go and read what was
agreed to. A refusal at the point of writing is recoverable; unverifiable evidence
discovered in a dispute is not.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.legal.constants import ASSENT_REQUIRED_SLUGS
from apps.legal.services import instruments as instruments_svc

logger = logging.getLogger("itrix")


class AssentRefused(Exception):
    """Raised when assent cannot be recorded. Never swallowed by a caller."""


def _require_open_transaction() -> None:
    """
    Refuse to run outside an atomic block.

    ── WHY THIS IS A HARD REFUSAL ──────────────────────────────────────────
    The guarantee is "a Client never exists without the assent that created it". If this
    function can be called outside the transaction that creates the Client, the guarantee
    degrades to "usually" — and the failure is invisible, because the happy path looks
    identical either way.

    ``get_connection().in_atomic_block`` is checked rather than trusted from a parameter,
    because a caller that had to declare it correctly is a caller that can declare it
    wrongly.
    """
    from django.db import connection

    if not connection.in_atomic_block:
        raise AssentRefused(
            "record_in_transaction must be called inside an atomic block, so the assent "
            "record and the Client land together or not at all "
            "(Architecture v2.8 §19.10). Wrap the caller in transaction.atomic()."
        )


def record_in_transaction(
    *,
    client=None,
    email: str = "",
    path: str,
    slugs=None,
    accepted_at_client=None,
    ip_address: str | None = None,
    user_agent: str = "",
):
    """
    Write the assent record. MUST be called inside the transaction that creates the Client.

    ``slugs`` defaults to the two instruments assent actually binds — Terms and Privacy.
    Security and Disclosure are STATEMENTS describing what the platform does; asking someone
    to "agree" to a description of our own security posture would be meaningless, and a
    record claiming they had would claim more than the checkbox showed them
    (Playbook v1.8 §18C).
    """
    from apps.legal.models import AssentRecord

    _require_open_transaction()

    try:
        entries = instruments_svc.current_versions(slugs or ASSENT_REQUIRED_SLUGS)
    except ValueError as exc:
        raise AssentRefused(str(exc)) from exc

    resolved_email = (email or getattr(client, "email", "") or "").strip()
    if not resolved_email and client is None:
        # Neither a subject nor an identifier. The record would name nobody.
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
    """
    Whether ``client`` has accepted the versions CURRENTLY in force.

    False after a material version change — which is what drives the re-prompt at next
    sign-in (§19.10). It compares versions rather than dates, because a date tells you when
    something changed and a version tells you what they agreed to.
    """
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
    """
    Every active Client with no assent record. SHOULD ALWAYS BE EMPTY.

    Exposed as a query rather than only a test, because the invariant is worth checking
    against production data and not only against fixtures. ``audit_assent`` runs it, and a
    non-empty result is a governance defect rather than a backlog item: those accounts exist
    without a recorded basis, and no amount of later work can reconstruct what they read.
    """
    from apps.clients.models import Client

    return Client.objects.filter(is_active=True, assent_records__isnull=True)
