"""
The migration report must run BEFORE ``migrate`` (Backend v6.0 §Phase 1).

── THE BUG THIS PINS ────────────────────────────────────────────────────────
``journey_migration_report`` is documented as the step you run FIRST, to review the
ENGAGED split before committing to it. But at that moment the Lead TABLE does not yet
have ``journey_number``, ``state_key``, ``persona_id``, ``first_thread_id`` or
``attachment_count`` — while the Lead MODEL already does.

A plain ``Lead.objects.filter(...)`` therefore emits
``SELECT ... "leads_lead"."journey_number" ...`` and dies with UndefinedColumn on
Postgres (``no such column`` on SQLite). The command was unusable at the only moment it
mattered.

The fix is to name columns explicitly with ``.values()``. These tests assert that the
generated SQL touches ONLY columns present in both schemas — which is the property that
actually matters, rather than the particular query style used to achieve it.
"""

from __future__ import annotations

import pytest

from apps.leads.models import Lead

pytestmark = pytest.mark.django_db

# Columns added by leads/0004_thread_spine. None of these exist when the report runs.
POST_MIGRATION_COLUMNS = (
    "journey_number",
    "state_key",
    "persona_id",
    "first_thread_id",
    "attachment_count",
)


def _sql(queryset) -> str:
    return str(queryset.query)


def test_the_engaged_queryset_touches_no_post_migration_column():
    """The exact query the report runs, asserted column-by-column."""
    sql = _sql(Lead.objects.filter(journey_state="ENGAGED").values("id", "company", "status"))
    for column in POST_MIGRATION_COLUMNS:
        assert column not in sql, f"report query selects {column}, which does not exist pre-migration"


def test_a_naive_queryset_would_have_failed():
    """
    Proves the test above is actually testing something.

    If this ever stops selecting the new columns, the guard above has become vacuous and
    should be re-examined rather than trusted.
    """
    sql = _sql(Lead.objects.filter(journey_state="ENGAGED"))
    assert "journey_number" in sql, (
        "the unrestricted queryset no longer selects journey_number — "
        "the column-safety guard may now be vacuous"
    )


def test_the_client_count_touches_no_columns():
    """``count()`` emits SELECT COUNT(*), so it is safe in both schemas."""
    sql = _sql(Lead.objects.filter(journey_state="CLIENT").values("id"))
    for column in POST_MIGRATION_COLUMNS:
        assert column not in sql


def test_evidence_lookups_use_lead_id_not_a_lead_instance():
    """
    Evidence queries filter on ``lead_id`` and use ``.exists()``.

    Passing a Lead INSTANCE would require loading it first, which re-introduces the
    original failure through the back door.
    """
    from apps.pocs.models import PoC

    sql = _sql(PoC.objects.filter(lead_id="00000000-0000-0000-0000-000000000000"))
    assert "leads_lead" not in sql, "evidence lookup must not join the leads table"


def test_the_report_classifier_accepts_a_values_dict():
    """The report classifies from a dict, not a model instance."""
    import importlib

    module = importlib.import_module(
        "apps.journey.management.commands.journey_migration_report"
    )
    command = module.Command()
    target, evidence = command._classify(
        {"id": "00000000-0000-0000-0000-000000000000", "status": "Licensed"}
    )
    assert target == "INTEGRATION"
    assert "Licensed" in evidence


def test_report_and_migration_classifiers_agree():
    """
    Two implementations of the same judgement must not drift.

    The report exists to predict what the migration will do. If they disagree, the
    review step is worse than useless — it is actively misleading.
    """
    import importlib

    from django.apps import apps as global_apps

    from tests.factories.lead_factory import LeadFactory

    report = importlib.import_module(
        "apps.journey.management.commands.journey_migration_report"
    ).Command()
    migration = importlib.import_module("apps.journey.migrations.0003_migrate_engaged_split")

    for status in ("Licensed", "Negotiation", "New", "Evaluation"):
        lead = LeadFactory(journey_state="ENGAGED", status=status)
        report_target, _evidence = report._classify(
            {"id": lead.id, "status": lead.status}
        )
        migration_target = migration.classify(global_apps, lead)
        assert report_target == migration_target, (
            f"status={status}: report says {report_target}, migration says {migration_target}"
        )


def test_the_report_runs_end_to_end():
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("journey_migration_report", stdout=out)
    assert "Journey migration report" in out.getvalue()
