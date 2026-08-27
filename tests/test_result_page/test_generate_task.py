"""
Tests for ``apps.result_page.tasks.generate_result_page_task`` — the Celery-preferred
result-page path.

The qualification processor imports this task by EXACT path when ENABLE_CELERY is on and
silently falls back to a daemon thread if the import fails. These tests therefore pin
three things: the import contract the processor depends on, the task's registered name,
and its behaviour (build/persist, missing-lead skip, bounded retry then quiet failure).
Everything runs eager (dev settings), which is also how ``.delay()`` behaves in tests.
"""

from __future__ import annotations

import pytest

from apps.result_page.models import ResultPage
from tests.factories.lead_factory import LeadFactory

pytestmark = pytest.mark.django_db


def test_import_contract_matches_qualification_processor():
    """The processor's exact import line must resolve — this is what un-deads the path."""
    from apps.result_page.tasks import generate_result_page_task  # noqa: PLC0415

    assert callable(generate_result_page_task)
    # Registered under a stable dotted name in the shared app registry.
    from tasks.celery import app

    assert "result_page.generate" in app.tasks


def test_builds_and_persists_result_page():
    lead = LeadFactory()
    from apps.result_page.tasks import generate_result_page_task

    result = generate_result_page_task.delay(str(lead.id))  # eager: runs inline
    payload = result.result

    assert payload["ok"] is True
    assert payload["lead_id"] == str(lead.id)
    page = ResultPage.objects.filter(lead=lead).first()
    assert page is not None
    assert payload["result_page_id"] == str(page.id)


def test_missing_lead_skips_without_retry():
    from apps.result_page.tasks import generate_result_page_task

    result = generate_result_page_task.delay("00000000-0000-0000-0000-000000000000")
    payload = result.result

    assert payload["ok"] is False
    # Task results are operational signals, not an exception-text transport.
    assert payload["error"] == "not_found"


def test_generator_failure_is_bounded_and_swallowed(monkeypatch):
    """A persistently failing build retries a bounded number of times, then returns a
    failure dict instead of raising — the /c page's on-demand regeneration is the
    recovery path, so the task must never poison the queue or crash a caller."""
    lead = LeadFactory()
    calls = {"n": 0}

    def _boom(self, lead, **kwargs):  # noqa: ANN001
        calls["n"] += 1
        raise RuntimeError("synthetic build failure")

    from apps.result_page.services.result_generator import ResultGenerator

    monkeypatch.setattr(ResultGenerator, "generate_for_lead", _boom)

    from apps.result_page.tasks import generate_result_page_task

    result = generate_result_page_task.apply(args=[str(lead.id)])
    payload = result.result

    assert payload["ok"] is False
    assert payload["error"] == "generation_failed"
    assert payload["status"] == "failed"
    # max_retries=2 → at most 3 attempts, and it must have retried at least once.
    assert 2 <= calls["n"] <= 3
