"""
Tests for the messaging + lead fan-out Celery integrations (2026-08-10).

Three contracts are pinned:

  1. A CLIENT portal message creates an in-app team notification (inline path,
     ENABLE_CELERY off — the default in tests), and a VISITOR message does not.
  2. With ENABLE_CELERY on, the same hook enqueues on commit; eager mode executes
     the task inline when the callbacks run, so the notification row still lands —
     proving the task path end to end without a broker.
  3. With ENABLE_CELERY on, the lead fan-out defers its two emails to on-commit
     task hand-off instead of sending inside the signal.

The `notifications.create` task's optional lead linkage is covered on the way.
"""

from __future__ import annotations

import pytest
from django.test import TestCase, override_settings

from apps.conversations.services import ingest
from apps.conversations.services.history import get_or_create_portal_conversation
from apps.notifications.models import Notification
from tests.factories.client_factory import ClientFactory

pytestmark = pytest.mark.django_db


def test_client_message_creates_team_notification_inline():
    client = ClientFactory()
    conv = get_or_create_portal_conversation(client)

    before = Notification.objects.count()
    ingest.ingest_inbound(conv, sender_kind="client", body="We reviewed the map.", client=client)

    assert Notification.objects.count() == before + 1
    created = Notification.objects.order_by("-created_at").first()
    assert "New client message" in created.title
    # A pointer, never the message: the body must not quote the client's words.
    assert "We reviewed the map." not in (created.body or "")
    assert created.href == f"/leads/{client.lead_id}"
    assert created.lead_id == client.lead_id


def test_visitor_message_creates_no_team_notification():
    client = ClientFactory()
    conv = get_or_create_portal_conversation(client)

    before = Notification.objects.count()
    ingest.ingest_inbound(conv, sender_kind="visitor", body="Anonymous question.")
    assert Notification.objects.count() == before


def test_notification_task_links_lead():
    from tasks.notification_tasks import create_notification_task
    from tests.factories.lead_factory import LeadFactory

    lead = LeadFactory()
    out = create_notification_task.delay("system", "t", "b", "/leads/x", lead_id=str(lead.id)).result
    n = Notification.objects.get(pk=out["notification_id"])
    assert n.lead_id == lead.id


class CeleryOnPathTests(TestCase):
    """on_commit paths need captureOnCommitCallbacks, hence TestCase style."""

    @override_settings(ENABLE_CELERY=True)
    def test_client_message_notification_enqueues_on_commit(self):
        client = ClientFactory()
        conv = get_or_create_portal_conversation(client)
        before = Notification.objects.count()

        with self.captureOnCommitCallbacks(execute=True):
            ingest.ingest_inbound(conv, sender_kind="client", body="Ping.", client=client)
            # Inside the transaction, nothing yet: the hand-off waits for commit.
            self.assertEqual(Notification.objects.count(), before)

        # Callbacks ran; eager mode executed the task inline. Row + lead FK landed.
        self.assertEqual(Notification.objects.count(), before + 1)
        created = Notification.objects.order_by("-created_at").first()
        self.assertEqual(created.lead_id, client.lead_id)

    @override_settings(ENABLE_CELERY=True)
    def test_lead_fanout_defers_emails_to_commit(self):
        from apps.emails.models import EmailLog
        from tests.factories.lead_factory import LeadFactory

        before = EmailLog.objects.count()
        with self.captureOnCommitCallbacks(execute=True):
            LeadFactory()  # post_save fan-out fires here
            # Emails must NOT have been built inside the signal.
            self.assertEqual(EmailLog.objects.count(), before)

        # On commit the eager tasks ran: internal alert + visitor confirmation.
        kinds = sorted(
            EmailLog.objects.order_by("created_at").values_list("kind", flat=True)[before:]
        )
        self.assertEqual(kinds, [EmailLog.Kind.CONFIRMATION, EmailLog.Kind.INTERNAL_ALERT])
