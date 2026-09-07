from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.knowledge_core.models import KnowledgeDocument
from apps.knowledge_core.services.pinecone_upserter import PineconeUpsertError

pytestmark = pytest.mark.django_db


def _doc(namespace: str, *, current: bool = True) -> KnowledgeDocument:
    return KnowledgeDocument.objects.create(
        title=f"{namespace}-{'current' if current else 'historical'}",
        namespace=namespace,
        is_current=current,
    )


def _upserter(before: dict[str, int], after: dict[str, int] | None = None):
    instance = Mock()
    instance.enabled = True
    instance.namespace_counts.side_effect = [before, after if after is not None else before]
    return instance


def _result(document: KnowledgeDocument):
    return SimpleNamespace(ok=True, document=document, error="")


def test_all_clears_and_reingests_current_namespace():
    current = _doc("current-x")
    remote = _upserter({"current-x": 7}, {"current-x": 3})
    out = StringIO()

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
        side_effect=lambda ns, dry_run=False: [_result(current)] if ns == "current-x" else [],
    ) as reconcile:
        call_command("reingest_namespace", "--all", stdout=out)

    assert call("current-x", dry_run=False) in reconcile.call_args_list
    assert "NAMESPACE=current-x REMOTE_BEFORE=7 CURRENT_DOCS=1" in out.getvalue()
    assert "REMOTE_AFTER=3 STATUS=OK" in out.getvalue()


def test_mixed_namespace_reingests_only_current_relational_documents():
    current = _doc("mixed-x", current=True)
    _doc("mixed-x", current=False)
    remote = _upserter({"mixed-x": 9}, {"mixed-x": 2})
    out = StringIO()

    def fake_reconcile(ns, dry_run=False):
        if ns != "mixed-x":
            return []
        # The service contract is current-only; the command reports the same authoritative
        # count rather than treating historical rows as re-ingest candidates.
        assert KnowledgeDocument.objects.filter(namespace=ns, is_current=True).count() == 1
        return [_result(current)]

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
        side_effect=fake_reconcile,
    ):
        call_command("reingest_namespace", "--all", stdout=out)

    assert "NAMESPACE=mixed-x REMOTE_BEFORE=9 CURRENT_DOCS=1" in out.getvalue()
    assert "REINGESTED=1 REMOTE_AFTER=2 STATUS=OK" in out.getvalue()


def test_stale_only_remote_namespace_is_discovered_cleared_and_left_empty():
    remote = _upserter({"legacy-x": 11}, {})
    out = StringIO()

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
        return_value=[],
    ) as reconcile:
        call_command("reingest_namespace", "--all", stdout=out)

    assert call("legacy-x", dry_run=False) in reconcile.call_args_list
    line = next(line for line in out.getvalue().splitlines() if "NAMESPACE=legacy-x" in line)
    assert "REMOTE_BEFORE=11" in line
    assert "CURRENT_DOCS=0" in line
    assert "DELETED/CLEARED=YES" in line
    assert "REINGESTED=0" in line
    assert "REMOTE_AFTER=0" in line
    assert "STATUS=OK" in line


def test_historical_db_only_namespace_is_explicitly_reconciled():
    _doc("historical-x", current=False)
    remote = _upserter({}, {})

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
        return_value=[],
    ) as reconcile:
        call_command("reingest_namespace", "--all")

    assert call("historical-x", dry_run=False) in reconcile.call_args_list


def test_all_never_discovers_or_touches_a_namespace_outside_configured_index_inventory():
    # namespace_counts() is intentionally index-scoped. A namespace that belongs to some
    # other account/index is absent from this inventory and therefore cannot be acted on.
    remote = _upserter({"inside-index": 1}, {})

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
        return_value=[],
    ) as reconcile:
        call_command("reingest_namespace", "--all")

    touched = {args[0] for args, _kwargs in reconcile.call_args_list}
    assert "inside-index" in touched
    assert "outside-other-index" not in touched


def test_remote_inventory_failure_is_explicit_and_never_reported_as_success():
    remote = Mock()
    remote.enabled = True
    remote.namespace_counts.side_effect = PineconeUpsertError("inventory unavailable")

    with patch(
        "apps.knowledge_core.management.commands.reingest_namespace.PineconeUpserter",
        return_value=remote,
    ), patch(
        "apps.knowledge_core.management.commands.reingest_namespace.reingest_namespace",
    ) as reconcile:
        with pytest.raises(CommandError, match="inventory unavailable"):
            call_command("reingest_namespace", "--all")

    reconcile.assert_not_called()
