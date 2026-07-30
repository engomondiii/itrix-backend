"""
NO CLIENT EXISTS WITHOUT THE ASSENT THAT CREATED IT (Architecture v2.8 §19.10, §11.6).

── WHY THIS IS ONE DATA-INTEGRITY TEST RATHER THAN ONE PER VIEW ─────────────

Asserting it view by view is asserting a habit. The invariant is a property of the DATA, and
the useful version of this test is the one a FOURTH door added later fails without anyone
remembering to write a test for it.

So the core assertion is a query: after exercising every path that can create a Client, are
there any Clients with no assent record? That question keeps working when someone adds a
door.
"""

from __future__ import annotations

import pytest

from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def _invitable_lead():
    """A Lead the journey gate will actually let through to a workspace."""
    from django.utils import timezone

    return LeadFactory(
        journey_state="INVITED",
        email="claimant@example.com",
        value_delivered_at=timezone.now(),
    )


def _mint_invite(lead):
    from apps.clients.services import invite

    return invite.mint_invite(lead)


# ─────────────────────────────────────────────────────────────────────────────
# THE INVARIANT
# ─────────────────────────────────────────────────────────────────────────────
def test_no_active_client_lacks_an_assent_record():
    """
    THE QUERY THAT KEEPS WORKING WHEN A FOURTH DOOR IS ADDED.

    ``clients_without_assent()`` is the same query ``audit_assent`` runs against production, so
    this test and that command cannot disagree about what the invariant means.
    """
    from apps.clients.services import invite
    from apps.legal.services import assent as assent_svc

    lead = _invitable_lead()
    client, _ = invite.claim_invite(
        _mint_invite(lead),
        email="claimant@example.com",
        password="a-long-enough-password",
        full_name="Sora Kim",
        organization="Example Corp",
    )
    assert client is not None
    assert assent_svc.clients_without_assent().count() == 0


def test_the_invite_claim_records_assent_in_the_same_transaction():
    from apps.clients.services import invite
    from apps.legal.models import AssentRecord

    lead = _invitable_lead()
    client, _ = invite.claim_invite(
        _mint_invite(lead), email="claimant@example.com", password="a-long-enough-password"
    )

    record = AssentRecord.objects.filter(client=client).first()
    assert record is not None
    assert record.path == AssentRecord.Path.INVITE_CLAIM


def test_a_failed_assent_record_takes_the_client_with_it():
    """
    THE PROPERTY THE WHOLE DESIGN EXISTS FOR.

    If the assent write raises, the Client must NOT survive. An account whose basis nobody can
    produce is precisely the state §19.10 exists to prevent, and it cannot be repaired later by
    guessing what the person read.
    """
    from unittest.mock import patch

    from apps.clients.models import Client
    from apps.clients.services import invite
    from apps.legal.services import assent as assent_svc

    lead = _invitable_lead()
    token = _mint_invite(lead)

    with patch.object(
        assent_svc, "record_in_transaction", side_effect=assent_svc.AssentRefused("no versions")
    ):
        with pytest.raises(invite.InviteError):
            invite.claim_invite(token, email="claimant@example.com", password="a-long-enough-password")

    assert not Client.objects.filter(lead=lead).exists(), (
        "a Client survived a failed assent write"
    )


@pytest.mark.django_db(transaction=True)
def test_recording_outside_a_transaction_is_refused():
    """
    The guarantee is "together or not at all". If this function could be called outside the
    transaction that creates the Client, the guarantee would degrade to "usually" — and the
    failure would be invisible, because the happy path looks identical either way.

    ── WHY THIS TEST NEEDS transaction=True, AND WHAT THAT REVEALED ─────────
    The ordinary ``django_db`` fixture wraps every test in an atomic block and rolls it back,
    so ``connection.in_atomic_block`` is ALWAYS True inside one — and the first version of this
    test passed the guard trivially without exercising it. ``transaction=True`` runs against a
    real committed connection, which is the only way to observe the guard at all.

    It is worth being precise about the guard's reach: it detects "no transaction is open",
    which is the common mistake. It CANNOT detect "a transaction is open but not the one that
    creates the Client" — and under ``ATOMIC_REQUESTS = True`` every view would satisfy it
    trivially. This deployment does not set ATOMIC_REQUESTS (Django's default is False), so the
    guard is live; if that ever changes, this guard becomes decorative and the invariant rests
    entirely on ``test_a_failed_assent_record_takes_the_client_with_it`` and on
    ``audit_assent`` run against production.
    """
    from apps.legal.services import assent as assent_svc

    with pytest.raises(assent_svc.AssentRefused) as exc:
        assent_svc.record_in_transaction(email="someone@example.com", path="reprompt")
    assert "atomic" in str(exc.value).lower()


def test_atomic_requests_is_not_enabled_so_the_guard_is_live():
    """
    Pins the assumption the guard above depends on.

    With ``ATOMIC_REQUESTS = True`` every view runs inside a transaction, and the guard would
    pass for any caller regardless of whether it is the transaction that creates the Client.
    If someone turns it on, this test fails and points at the note above rather than letting
    the guard quietly become decorative.
    """
    from django.conf import settings

    for alias, config in (settings.DATABASES or {}).items():
        assert not config.get("ATOMIC_REQUESTS", False), (
            f"ATOMIC_REQUESTS is on for '{alias}'. The in_atomic_block guard in "
            "apps/legal/services/assent.py is now trivially satisfied — see its docstring."
        )


# ─────────────────────────────────────────────────────────────────────────────
# What the record stores
# ─────────────────────────────────────────────────────────────────────────────
def test_the_record_stores_versions_not_a_boolean():
    """
    The entire design. A boolean cannot answer "what exactly did this customer agree to?" once
    the Terms have changed.
    """
    from django.db import transaction

    from apps.legal.services import assent as assent_svc

    with transaction.atomic():
        record = assent_svc.record_in_transaction(email="v@example.com", path="reprompt")

    assert record.instruments, "no instrument versions were stored"
    for entry in record.instruments:
        assert entry["slug"]
        assert entry["version"], "an assent record with version '' is unverifiable"
    assert record.version_of("terms")
    assert record.version_of("privacy")


def test_assent_binds_terms_and_privacy_only():
    """
    Security and Disclosure are STATEMENTS describing what the platform does. Asking someone to
    "agree" to a description of our own security posture would be meaningless, and a record
    claiming they had would claim more than the checkbox showed them (Playbook v1.8 §18C).
    """
    from django.db import transaction

    from apps.legal.services import assent as assent_svc

    with transaction.atomic():
        record = assent_svc.record_in_transaction(email="v@example.com", path="reprompt")

    assert set(record.accepted_slugs) == {"terms", "privacy"}


def test_an_unknown_instrument_is_refused():
    """
    An assent record naming an instrument the platform does not publish is unverifiable — you
    cannot go and read what was agreed to. Storing it would create evidence that proves nothing
    while looking like it proves something.
    """
    from django.db import transaction

    from apps.legal.services import assent as assent_svc

    with transaction.atomic():
        with pytest.raises(assent_svc.AssentRefused):
            assent_svc.record_in_transaction(
                email="v@example.com", path="reprompt", slugs=["terms", "not-an-instrument"]
            )


def test_a_missing_version_is_refused(settings):
    """A record naming version '' looks like evidence and proves nothing."""
    from django.db import transaction

    from apps.legal.services import assent as assent_svc

    settings.LEGAL_TERMS_VERSION = ""
    with transaction.atomic():
        with pytest.raises(assent_svc.AssentRefused) as exc:
            assent_svc.record_in_transaction(email="v@example.com", path="reprompt")
    assert "unverifiable" in str(exc.value).lower()


def test_a_record_with_neither_client_nor_email_is_refused():
    from django.db import transaction

    from apps.legal.services import assent as assent_svc

    with transaction.atomic():
        with pytest.raises(assent_svc.AssentRefused):
            assent_svc.record_in_transaction(path="reprompt")


# ─────────────────────────────────────────────────────────────────────────────
# The record outlives the account
# ─────────────────────────────────────────────────────────────────────────────
def test_the_record_survives_the_client_being_deleted():
    """
    A dispute about what someone agreed to does not become moot because they closed their
    workspace. The FK is SET_NULL and the email is denormalised, because a record with a null
    FK and no other identifier is evidence of nothing.
    """
    from apps.clients.services import invite
    from apps.legal.models import AssentRecord

    lead = _invitable_lead()
    client, _ = invite.claim_invite(
        _mint_invite(lead), email="claimant@example.com", password="a-long-enough-password"
    )
    record_id = AssentRecord.objects.get(client=client).id
    client.delete()

    record = AssentRecord.objects.get(id=record_id)
    assert record.client_id is None
    assert record.client_email_at_assent == "claimant@example.com"
    assert record.instruments


# ─────────────────────────────────────────────────────────────────────────────
# Version drift and the re-prompt
# ─────────────────────────────────────────────────────────────────────────────
def test_has_current_assent_goes_false_after_a_version_change(settings):
    """
    This is what drives the re-prompt at next sign-in. It compares VERSIONS rather than dates,
    because a date says when something changed and a version says what they agreed to.
    """
    from apps.clients.services import invite
    from apps.legal.services import assent as assent_svc

    lead = _invitable_lead()
    client, _ = invite.claim_invite(
        _mint_invite(lead), email="claimant@example.com", password="a-long-enough-password"
    )
    assert assent_svc.has_current_assent(client) is True

    settings.LEGAL_TERMS_VERSION = "2.0"
    assert assent_svc.has_current_assent(client) is False


def test_a_client_with_no_record_has_no_current_assent():
    from tests.factories.client_factory import ClientFactory

    from apps.legal.services import assent as assent_svc

    assert assent_svc.has_current_assent(ClientFactory()) is False
