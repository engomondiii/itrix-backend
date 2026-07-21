"""
"What changed since you were last here" (Playbook §12E).

The clause that makes it honest: "and anything waiting on a decision FROM YOU". A digest
of only our own completed work is a progress report that hides the item the customer most
needs to see.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.customer_success.models import ChangeLogEntry
from apps.customer_success.services import change_digest

pytestmark = pytest.mark.django_db


def test_an_empty_digest_says_so_plainly(paying_client):
    digest = change_digest.build(paying_client)
    assert digest["entries"] == []
    assert digest["empty_state"] == "Nothing has changed since your last visit."


def test_items_awaiting_the_customer_are_returned_separately_and_first(paying_client):
    """
    Mixing them into a reverse-chronological feed buries the one thing they must act on.
    """
    change_digest.record(paying_client, kind=ChangeLogEntry.Kind.COMPLETED,
                         title="Finished the baseline run")
    change_digest.record(paying_client, kind=ChangeLogEntry.Kind.AWAITING_DECISION,
                         title="Confirm the agreed benchmark")

    digest = change_digest.build(paying_client, since=timezone.now() - timezone.timedelta(days=1))
    assert len(digest["awaiting_decision"]) == 1
    assert digest["awaiting_decision"][0]["title"] == "Confirm the agreed benchmark"
    assert all(e["kind"] != "awaiting_decision" for e in digest["entries"])


def test_the_window_defaults_to_the_last_visit(paying_client):
    """
    "Since you were last here" means since THEIR last visit — not since we last generated
    a digest.
    """
    paying_client.last_login_at = timezone.now() - timezone.timedelta(days=2)
    paying_client.save(update_fields=["last_login_at"])

    change_digest.record(paying_client, kind=ChangeLogEntry.Kind.SHIPPED, title="Recent",
                         occurred_at=timezone.now())
    change_digest.record(paying_client, kind=ChangeLogEntry.Kind.SHIPPED, title="Ancient",
                         occurred_at=timezone.now() - timezone.timedelta(days=30))

    titles = [e["title"] for e in change_digest.build(paying_client)["entries"]]
    assert "Recent" in titles
    assert "Ancient" not in titles


def test_the_empty_state_is_absent_when_there_is_news(paying_client):
    change_digest.record(paying_client, kind=ChangeLogEntry.Kind.RESOLVED, title="Fixed it")
    assert change_digest.build(paying_client)["empty_state"] == ""
