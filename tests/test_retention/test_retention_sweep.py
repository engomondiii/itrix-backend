"""
THE RETENTION SWEEP COMMAND (Backend v7.1 Phase 3).

── WHY A COMMAND WAS THE GAP ───────────────────────────────────────────────

The sweeps have existed since v6.0. ``ENABLE_CELERY`` is False in the deployed environment,
so nothing calls them — which means the retention promise in the Privacy Policy was a
statement about code that never ran.

A cron entry running this command makes the promise true without requiring the whole Celery
deployment. These tests pin the two properties that matter: ``--dry-run`` touches nothing, and
assent records are never swept.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run(*args) -> str:
    out = StringIO()
    call_command("retention_sweep", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def test_dry_run_changes_nothing():
    """Retention is irreversible. The first run against real data should be read before it is trusted."""
    from apps.conversations.services import threads as thread_svc

    thread = thread_svc.create_thread(visitor_session="sess-retention")
    output = _run("--dry-run")

    assert "DRY RUN" in output
    from apps.conversations.models import Thread

    assert Thread.objects.filter(id=thread.id).exists()


def test_it_prints_the_windows_in_force():
    """
    These numbers are quoted in the Privacy Policy §8. Printing them lets an operator see whether
    the deployment agrees with the document — and a mismatch there is a published promise the code
    is not keeping.
    """
    output = _run("--dry-run")
    for name in ("ANON_THREAD_RETENTION_DAYS", "PRE_NDA_ATTACHMENT_RETENTION_DAYS"):
        assert name in output


def test_assent_records_are_never_swept():
    """
    Stated in the output rather than left as an absence, because "the sweep does not touch this
    table" is exactly what a future maintainer would add for consistency.

    Evidence of what a customer agreed to has to outlive the account (§19.10). The record holds an
    email, a version, a timestamp and an IP — no conversation content, no attachment, nothing
    about their work.
    """
    from django.db import transaction

    from apps.legal.models import AssentRecord
    from apps.legal.services import assent as assent_svc

    with transaction.atomic():
        assent_svc.record_in_transaction(email="keep@example.com", path="reprompt")

    output = _run()
    assert "NOT swept" in output
    assert AssentRecord.objects.filter(client_email_at_assent="keep@example.com").exists()


def test_a_broken_subsystem_does_not_stop_the_other_sweep():
    """
    One unavailable sweep must not silently skip the other. Retention is the kind of guarantee that
    fails quietly, so a partial run has to say which half ran.
    """
    from unittest.mock import patch

    with patch(
        "apps.conversations.services.retention.expired_threads",
        side_effect=RuntimeError("db gone"),
    ):
        output = _run("--dry-run")

    assert "Attachments past retention" in output


def test_the_audit_command_reports_a_clean_invariant():
    from io import StringIO

    out = StringIO()
    call_command("audit_assent", stdout=out, stderr=StringIO())
    body = out.getvalue()
    assert "Versions in force" in body
    assert "assent record" in body


def test_the_audit_command_names_clients_with_no_record():
    """
    A non-empty result is a governance DEFECT, not a backlog item — and the command says so,
    including that backfilling would be worse than the gap.
    """
    from io import StringIO

    from tests.factories.client_factory import ClientFactory

    ClientFactory(email="norecord@example.com", is_active=True)

    out = StringIO()
    call_command("audit_assent", stdout=out, stderr=StringIO())
    body = out.getvalue()
    assert "NO assent record" in body
    assert "GOVERNANCE DEFECT" in body
    assert "Do NOT backfill" in body
