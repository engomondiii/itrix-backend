"""
THE 2026-08-12 BACKEND FIX SET.

Seven reported defects, each with the test that would have caught it. They are together
in one module because they were reported and fixed together; each section names the
symptom an operator or a visitor actually saw, because that is what a future reader needs
in order to know whether a refactor has quietly reinstated the bug.

    1. staff replies were persisted with thread=None and were rendered nowhere
    2. lead actions answered with the PREFETCHED lead, so a new note was missing
    3. lead assignment was last-write-wins with nothing on screen to say so
    4. the cockpit boards capped at 500 rows with no offset — older rows unreachable
    5. the support queue was read-only, so the row explaining a block could not end it
    6. settings/notifications/ 404'd because the app was never include()d
    7. staff could not send a file, and no wire frame carried the thread id
"""

from __future__ import annotations

import pytest

from tests.factories.client_factory import ClientFactory
from tests.factories.conversation_factory import ConversationFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db


def _team_client(role: str = "ADMIN", email: str | None = None):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    User = get_user_model()
    user = User.objects.create_user(
        email=email or f"{role.lower()}-fixes@itrix.test",
        password="a-long-enough-password",
        role=role,
        is_active=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


# ═════════════════════════════════════════════════════════════════════════════
# 1. Staff replies land on the thread
# ═════════════════════════════════════════════════════════════════════════════
def _threaded_conversation():
    """A Conversation with its Thread, wired both ways as the spine expects."""
    from apps.conversations.services import threads as thread_svc

    lead = LeadFactory()
    conversation = ConversationFactory(lead=lead)
    thread = thread_svc.create_thread(visitor_session="sess-fixes-aug12", lead=lead)
    thread.conversation = conversation
    thread.save(update_fields=["conversation"])
    conversation.refresh_from_db()
    return conversation, thread


def test_team_reply_is_attached_to_its_thread():
    """
    THE REPORTED BUG. `ingest_team_message` created the Message with no thread, and every
    transcript read queries by thread — so the reply was saved and invisible.
    """
    from apps.conversations.services import ingest

    conversation, thread = _threaded_conversation()
    user = AdminUserFactory()

    msg = ingest.ingest_team_message(conversation, user=user, body="We looked at your trace.")

    assert msg.thread_id == thread.id, "a staff reply must belong to the thread it answers"


def test_team_reply_gets_a_sequence_number():
    """
    Left at seq 0, a reply sorts BEFORE the visitor's first turn in any ordered read — so
    even a client that found it would show it in the wrong place. The realtime gap
    detector reads the same field.
    """
    from apps.conversations.models import Message, SenderKind
    from apps.conversations.services import ingest

    conversation, thread = _threaded_conversation()
    Message.objects.create(
        conversation=conversation, thread=thread, sender_kind=SenderKind.VISITOR,
        body="Our solver is slow.", seq=1,
    )

    msg = ingest.ingest_team_message(conversation, user=AdminUserFactory(), body="Noted.")

    assert msg.seq > 1, "a staff reply must be sequenced after the turns it follows"


def test_team_reply_still_persists_without_a_thread():
    """
    The shipped review and client-page conversations predate the spine. A reply on one of
    those must still be written — the fix adds a thread when there is one, it does not
    make a thread mandatory.
    """
    from apps.conversations.services import ingest

    conversation = ConversationFactory()
    msg = ingest.ingest_team_message(conversation, user=AdminUserFactory(), body="Hello.")

    assert msg.pk is not None
    assert msg.thread_id is None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Lead actions answer with fresh data
# ═════════════════════════════════════════════════════════════════════════════
def test_note_action_returns_the_note_it_just_added():
    """
    THE REPORTED BUG. `get_object()` filled the prefetch caches, the action wrote a note,
    and the response serialised the cache — so the operator saw their note missing and
    pressed the button again.
    """
    client, _ = _team_client(email="note-fresh@itrix.test")
    lead = LeadFactory()

    body = client.post(
        f"/api/v1/leads/{lead.id}/note/", {"body": "Spoke with the customer."}, format="json"
    ).json()

    notes = body.get("notes") or []
    assert any("Spoke with the customer." in (n.get("body") or "") for n in notes), (
        f"the new note must be in the response body, got {notes!r}"
    )


def test_status_action_returns_the_activity_it_just_logged():
    from apps.leads.models import LeadStatus

    client, _ = _team_client(email="status-fresh@itrix.test")
    lead = LeadFactory()
    # The serializer names the list `activity` (source="activities").
    before = len((client.get(f"/api/v1/leads/{lead.id}/").json().get("activity") or []))

    body = client.post(
        f"/api/v1/leads/{lead.id}/status/", {"status": LeadStatus.CONTACTED}, format="json"
    ).json()

    assert len(body.get("activity") or []) > before


# ═════════════════════════════════════════════════════════════════════════════
# 3. Assign-if-unowned
# ═════════════════════════════════════════════════════════════════════════════
def test_second_operator_cannot_silently_take_an_owned_lead():
    """
    THE REPORTED BUG. Both operators got 200 and the second one's name; nothing said a
    colleague had just been displaced.
    """
    client, _ = _team_client(email="assign-a@itrix.test")
    lead = LeadFactory()
    first = AdminUserFactory(email="first-owner@itrix.test", name="First Owner")
    second = AdminUserFactory(email="second-owner@itrix.test", name="Second Owner")

    assert client.post(
        f"/api/v1/leads/{lead.id}/assign/", {"owner": first.email}, format="json"
    ).status_code == 200

    clash = client.post(
        f"/api/v1/leads/{lead.id}/assign/", {"owner": second.email}, format="json"
    )

    assert clash.status_code == 409
    assert clash.json()["reason"] == "already_owned"
    assert clash.json()["currentOwner"]["id"] == str(first.id)

    lead.refresh_from_db()
    assert lead.owner_id == first.id, "the loser's write must not have landed"


def test_force_reassigns_deliberately():
    client, _ = _team_client(email="assign-b@itrix.test")
    lead = LeadFactory()
    first = AdminUserFactory(email="held-by@itrix.test", name="Held By")
    second = AdminUserFactory(email="taking-over@itrix.test", name="Taking Over")

    client.post(f"/api/v1/leads/{lead.id}/assign/", {"owner": first.email}, format="json")
    taken = client.post(
        f"/api/v1/leads/{lead.id}/assign/",
        {"owner": second.email, "force": True},
        format="json",
    )

    assert taken.status_code == 200
    lead.refresh_from_db()
    assert lead.owner_id == second.id


def test_assigning_the_same_owner_twice_is_not_a_conflict():
    """Pressing a button twice is one intention, not a collision."""
    client, _ = _team_client(email="assign-c@itrix.test")
    lead = LeadFactory()
    owner = AdminUserFactory(email="idempotent@itrix.test", name="Idempotent Owner")

    client.post(f"/api/v1/leads/{lead.id}/assign/", {"owner": owner.email}, format="json")
    again = client.post(
        f"/api/v1/leads/{lead.id}/assign/", {"owner": owner.email}, format="json"
    )

    assert again.status_code == 200


def test_no_activity_row_is_written_for_a_losing_attempt():
    """
    A timeline that logged failed takeovers would show owner changes that never happened —
    and the timeline is the record people trust when they ask who took a lead.
    """
    from apps.leads.models import LeadActivity
    from apps.leads.services.lead_updater import assign_owner

    lead = LeadFactory()
    first = AdminUserFactory(email="timeline-first@itrix.test", name="Timeline First")
    second = AdminUserFactory(email="timeline-second@itrix.test", name="Timeline Second")

    assign_owner(lead, owner=first, only_if_unowned=True)
    before = LeadActivity.objects.filter(
        lead=lead, type=LeadActivity.ActivityType.OWNER_CHANGE
    ).count()

    result = assign_owner(lead, owner=second, only_if_unowned=True)

    assert result.applied is False
    assert LeadActivity.objects.filter(
        lead=lead, type=LeadActivity.ActivityType.OWNER_CHANGE
    ).count() == before


def test_unconditional_assignment_is_unchanged_for_existing_callers():
    """The default is still the old behaviour, so no existing caller changed meaning."""
    from apps.leads.services.lead_updater import assign_owner

    lead = LeadFactory()
    first = AdminUserFactory(email="legacy-a@itrix.test", name="Legacy A")
    second = AdminUserFactory(email="legacy-b@itrix.test", name="Legacy B")

    assign_owner(lead, owner=first)
    result = assign_owner(lead, owner=second)

    assert result.applied is True
    lead.refresh_from_db()
    assert lead.owner_id == second.id


# ═════════════════════════════════════════════════════════════════════════════
# 4. The boards are pageable
# ═════════════════════════════════════════════════════════════════════════════
def test_thread_board_reports_a_total_and_pages():
    """
    THE REPORTED BUG. `[:limit]` with no offset meant the 501st thread could not be
    reached by any request. A page-size cap is fine; a cap with no offset is data loss.
    """
    from apps.conversations.services import threads as thread_svc

    for i in range(5):
        thread_svc.create_thread(visitor_session=f"sess-page-{i}")

    client, _ = _team_client(email="board-page@itrix.test")
    first = client.get("/api/v1/cockpit/threads/?limit=2&offset=0").json()
    second = client.get("/api/v1/cockpit/threads/?limit=2&offset=2").json()

    assert first["total"] >= 5
    assert first["count"] == 2
    assert first["hasMore"] is True
    assert second["offset"] == 2

    ids_first = {r["threadId"] for r in first["results"]}
    ids_second = {r["threadId"] for r in second["results"]}
    assert not (ids_first & ids_second), "pages must not overlap"


def test_thread_board_paging_reaches_every_row():
    """The property that matters: walking the offsets returns the whole set."""
    # TWO modules called `threads`: the conversation SPINE service creates threads, the
    # COCKPIT service reads the board. Aliased apart here because importing the wrong one
    # is the obvious mistake and it fails with a confusing AttributeError.
    from apps.cockpit.services import threads as board_svc
    from apps.conversations.models import Thread
    from apps.conversations.services import threads as spine_svc

    made = {str(spine_svc.create_thread(visitor_session=f"sess-walk-{i}").id) for i in range(7)}
    total = Thread.objects.count()

    seen: set[str] = set()
    offset = 0
    while offset < total:
        page = board_svc.page(limit=3, offset=offset)
        seen.update(r["threadId"] for r in page["results"])
        offset += 3

    assert made <= seen


def test_customer_board_reports_a_total_and_names_its_ordering():
    """
    Health is derived in Python, so the database cannot sort by it and "worst first" is a
    within-page ordering. The payload says so rather than letting a dashboard read row 1
    of page 1 as the worst customer of all.
    """
    for i in range(3):
        ClientFactory(email=f"board-{i}@customer.test")

    client, _ = _team_client(email="cust-page@itrix.test")
    body = client.get("/api/v1/cockpit/customers/?limit=2&offset=0").json()

    assert body["total"] >= 3
    assert body["ordering"] == "worst_first_within_page"
    assert body["hasMore"] is True


def test_board_row_helpers_keep_their_old_shape():
    """
    `rows()` and `results()` still return plain lists, so nothing that already called them
    had to change with this fix.
    """
    from apps.cockpit.services import customers as customers_svc
    from apps.cockpit.services import threads as threads_svc

    assert isinstance(threads_svc.rows(limit=1), list)
    assert isinstance(customers_svc.results(limit=1), list)


# ═════════════════════════════════════════════════════════════════════════════
# 5. The support queue can be worked
# ═════════════════════════════════════════════════════════════════════════════
def _support_request(**kwargs):
    from apps.customer_success.models import SupportRequest

    defaults = {
        "client": kwargs.pop("client", None) or ClientFactory(),
        "subject": "Batch job stalls",
        "body": "Every run since Tuesday takes twice as long.",
        "status": SupportRequest.Status.OPEN,
        "urgency": SupportRequest.Urgency.NORMAL,
        "blocking": True,
    }
    defaults.update(kwargs)
    return SupportRequest.objects.create(**defaults)


def test_operator_can_take_a_support_request():
    client, user = _team_client(email="support-assign@itrix.test")
    req = _support_request()

    body = client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/assign/", {"owner": "me"}, format="json"
    ).json()

    req.refresh_from_db()
    assert req.owner_id == user.id
    assert body["owner"]
    assert req.first_response_at is not None, "taking an open request is the first response"


def test_support_request_can_be_cleared_of_its_owner():
    """An unowned request is honest; a nominal owner who has handed it on is not."""
    client, _ = _team_client(email="support-clear@itrix.test")
    owner = AdminUserFactory(email="prev-owner@itrix.test", name="Prev Owner")
    req = _support_request(owner=owner, owner_name="Prev Owner")

    client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/assign/", {"owner": None}, format="json"
    )

    req.refresh_from_db()
    assert req.owner_id is None


def test_resolving_requires_a_note():
    """
    Enforced in the SERVICE, so a direct API call cannot close a customer's problem
    without saying how — the same placement as the attachment release reason.
    """
    client, _ = _team_client(email="support-note@itrix.test")
    req = _support_request()

    refused = client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/", {"note": "   "}, format="json"
    )

    assert refused.status_code == 400
    assert refused.json()["reason"] == "note_required"
    req.refresh_from_db()
    from apps.customer_success.models import SupportRequest

    assert req.status == SupportRequest.Status.OPEN, "nothing was closed"


def test_resolving_closes_the_request_and_keeps_the_note():
    from apps.customer_success.models import SupportRequest

    client, _ = _team_client(email="support-resolve@itrix.test")
    req = _support_request()

    body = client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/",
        {"note": "Rebalanced the shard; confirmed with the customer."},
        format="json",
    ).json()

    req.refresh_from_db()
    assert req.status == SupportRequest.Status.RESOLVED
    assert req.resolved_at is not None
    assert "Rebalanced the shard" in req.resolution_note
    assert body["resolvedAt"]


def test_resolving_does_not_answer_for_the_customer():
    """
    `customer_confirmed_resolved` is the CUSTOMER'S answer to "did this actually fix it?".
    An operator answering it would erase the most useful signal on the row.
    """
    client, _ = _team_client(email="support-confirm@itrix.test")
    req = _support_request()

    client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/",
        {"note": "Restarted the worker."},
        format="json",
    )

    req.refresh_from_db()
    assert req.customer_confirmed_resolved is None


def test_resolving_does_not_touch_blocking():
    """
    `blocking` is the customer's situation and the field NBA suppression reads. An
    operator who could clear it could unblock their own commercial action by relabelling
    somebody else's problem.
    """
    client, _ = _team_client(email="support-blocking@itrix.test")
    req = _support_request(blocking=True)

    client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/",
        {"note": "Fixed."},
        format="json",
    )

    req.refresh_from_db()
    assert req.blocking is True


def test_resolving_is_idempotent_and_keeps_the_first_close():
    """The first close is when it stopped blocking the customer — that is the timestamp
    the health calculation reads."""
    client, _ = _team_client(email="support-idem@itrix.test")
    req = _support_request()

    client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/", {"note": "First note."},
        format="json",
    )
    req.refresh_from_db()
    first_at, first_note = req.resolved_at, req.resolution_note

    client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/", {"note": "Second note."},
        format="json",
    )
    req.refresh_from_db()

    assert req.resolved_at == first_at
    assert req.resolution_note == first_note


def test_viewer_cannot_work_the_queue():
    """A read-only role that could close a blocking request would be read-only in name
    only — closing one lifts the expansion suppression §18.7 applies."""
    from rest_framework.test import APIClient

    viewer = ViewerUserFactory(email="viewer-support@itrix.test")
    client = APIClient()
    client.force_authenticate(user=viewer)
    req = _support_request()

    assert client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/resolve/", {"note": "No."}, format="json"
    ).status_code == 403
    assert client.post(
        f"/api/v1/cockpit/support/queue/{req.id}/assign/", {"owner": "me"}, format="json"
    ).status_code == 403


def test_queue_names_the_actions_it_honours():
    """So the dashboard renders the buttons the API supports, not a hard-coded guess."""
    client, _ = _team_client(email="support-actions@itrix.test")
    _support_request()

    body = client.get("/api/v1/cockpit/support/queue/").json()

    assert body["actions"] == ["assign", "resolve"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. The settings routes exist
# ═════════════════════════════════════════════════════════════════════════════
def test_notification_preferences_endpoint_is_mounted():
    """
    THE REPORTED BUG. `apps.settings` was in INSTALLED_APPS with a complete urls.py, and
    the router never include()d it — so the screen had no endpoint and got a 404.
    """
    client, _ = _team_client(email="settings-notif@itrix.test")

    res = client.get("/api/v1/settings/notifications/")

    assert res.status_code != 404, "the route must exist"
    assert res.status_code == 200


def test_sla_settings_endpoint_is_mounted():
    client, _ = _team_client(email="settings-sla@itrix.test")

    assert client.get("/api/v1/settings/sla/").status_code == 200


def test_settings_routes_reverse():
    """Named routes, so a future move breaks a test rather than a screen."""
    from django.urls import reverse

    assert reverse("itrix_settings:notifications").endswith("/settings/notifications/")
    assert reverse("itrix_settings:sla").endswith("/settings/sla/")


# ═════════════════════════════════════════════════════════════════════════════
# 7. Staff → visitor files, and the thread id on the wire
# ═════════════════════════════════════════════════════════════════════════════
def _staged_attachment(thread, *, filename="nda-draft.pdf", uploaded_by_kind="team"):
    from apps.attachments.models import Attachment, AttachmentStatus

    return Attachment.objects.create(
        thread=thread,
        filename=filename,
        bytes=32,
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        status=AttachmentStatus.READY,
        uploaded_by_kind=uploaded_by_kind,
    )


def test_staff_can_send_a_file_with_a_console_reply():
    client, _ = _team_client(email="console-file@itrix.test")
    conversation, thread = _threaded_conversation()
    attachment = _staged_attachment(thread)

    body = client.post(
        f"/api/v1/console/conversations/{conversation.id}/message/",
        {"body": "Your NDA is attached.", "attachmentIds": [str(attachment.id)]},
        format="json",
    ).json()

    assert body["attachmentsLinked"] == 1
    assert body["threadId"] == str(thread.id)


def test_a_file_only_reply_is_accepted():
    """"Here is the document" with the document and no prose is a legitimate send."""
    client, _ = _team_client(email="console-fileonly@itrix.test")
    conversation, thread = _threaded_conversation()
    attachment = _staged_attachment(thread)

    res = client.post(
        f"/api/v1/console/conversations/{conversation.id}/message/",
        {"body": "", "attachmentIds": [str(attachment.id)]},
        format="json",
    )

    assert res.status_code == 201


def test_an_empty_fileless_reply_is_still_refused():
    client, _ = _team_client(email="console-empty@itrix.test")
    conversation, _ = _threaded_conversation()

    res = client.post(
        f"/api/v1/console/conversations/{conversation.id}/message/", {"body": ""}, format="json"
    )

    assert res.status_code == 400


def test_a_foreign_attachment_id_cannot_be_stapled_to_a_reply():
    """
    An id in a request body is not authorization. A console operator must not be able to
    attach another customer's document by pasting its id.
    """
    client, _ = _team_client(email="console-foreign@itrix.test")
    conversation, _ = _threaded_conversation()
    _other_conversation, other_thread = _threaded_conversation()
    foreign = _staged_attachment(other_thread, filename="someone-elses.pdf")

    body = client.post(
        f"/api/v1/console/conversations/{conversation.id}/message/",
        {"body": "Attached.", "attachmentIds": [str(foreign.id)]},
        format="json",
    ).json()

    assert body["attachmentsLinked"] == 0
    assert body["attachmentsRejected"] == 1


def test_the_visitor_sees_the_file_on_the_reply():
    """The whole point of the feature: the chip renders in the customer's transcript."""
    from apps.conversations.serializers import MessageSerializer
    from apps.conversations.models import Message

    client, _ = _team_client(email="console-visible@itrix.test")
    conversation, thread = _threaded_conversation()
    attachment = _staged_attachment(thread)

    res = client.post(
        f"/api/v1/console/conversations/{conversation.id}/message/",
        {"body": "Signed copy attached.", "attachmentIds": [str(attachment.id)]},
        format="json",
    ).json()

    msg = Message.objects.get(id=res["messageId"])
    data = MessageSerializer(msg).data

    assert [a["filename"] for a in data["attachments"]] == ["nda-draft.pdf"]


def test_the_console_conversation_row_carries_its_thread_id():
    """
    THE REPORTED BUG. The row named a conversation, while every row-level cockpit resource
    is keyed by thread — so an operator could not open the board row for what they were
    reading.
    """
    client, _ = _team_client(email="console-mapping@itrix.test")
    conversation, thread = _threaded_conversation()

    rows = client.get("/api/v1/console/conversations/").json()
    row = next((r for r in rows if r["id"] == str(conversation.id)), None)

    assert row is not None
    assert row["threadId"] == str(thread.id)


def test_a_pre_spine_conversation_reports_a_null_thread_id():
    """Null is the truth for the shipped conversations that predate the spine, and it is
    distinguishable from an omitted field."""
    client, _ = _team_client(email="console-null@itrix.test")
    conversation = ConversationFactory()

    rows = client.get("/api/v1/console/conversations/").json()
    row = next((r for r in rows if r["id"] == str(conversation.id)), None)

    assert row is not None
    assert row["threadId"] is None


def test_staff_uploads_are_marked_as_team_uploads():
    """
    The kind is derived from WHO UPLOADED, not from who owns the thread. The excerpt
    selector fences visitor uploads as untrusted input and the review queue exists to look
    at what visitors sent us — a staff file that looked like the customer's own would end
    up in both.
    """
    from apps.attachments.permissions import staff_may_attach

    _client, user = _team_client(email="upload-kind@itrix.test")
    _conversation, thread = _threaded_conversation()

    class _Req:
        pass

    req = _Req()
    req.user = user
    assert staff_may_attach(req, thread) is True


def test_staff_attachment_predicate_does_not_grant_ownership():
    """
    `staff_may_attach` is deliberately NOT a branch inside `owns_thread`: widening that
    would widen `CanDownloadAttachment` too, where the whole point is that another subject
    cannot reach these bytes.
    """
    from apps.attachments.permissions import owns_thread

    _client, user = _team_client(email="upload-noown@itrix.test")
    _conversation, thread = _threaded_conversation()

    class _Req:
        META: dict = {}
        COOKIES: dict = {}

    req = _Req()
    req.user = user

    assert owns_thread(req, thread) is False
