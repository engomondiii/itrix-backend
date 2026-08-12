"""
THE TEAM UPLOAD PLANE (staff → visitor files, 2026-08-12).

A team member can put a document into a customer's thread from the console. That needed
a second authenticator on the upload view, and adding one to a view that ALSO authenticates
clients is where this feature can go wrong — so the properties are pinned here rather than
left to the feature test.

── THE MISTAKE THIS MODULE EXISTS TO PREVENT ────────────────────────────────
The first draft asked `core.permissions._is_active_team_member`, which is
`authenticated and active`. On a team-only view that is a correct team check, because
`request.user` can only be a team User there. On THIS view `request.user` may be a
Client — and a Client is authenticated and active. Every signed-in customer therefore
passed as staff and could attach a file to any thread, including another customer's.

`test_a_client_is_never_a_team_caller` is that bug, as a test.
"""

from __future__ import annotations

import pytest

from tests.factories.client_factory import ClientFactory
from tests.factories.conversation_factory import ConversationFactory
from tests.factories.lead_factory import LeadFactory
from tests.factories.user_factory import AdminUserFactory, ViewerUserFactory

pytestmark = pytest.mark.django_db


class _Req:
    """A request stand-in. The predicates read `user`, `META` and `COOKIES` only."""

    def __init__(self, user):
        self.user = user
        self.META: dict = {}
        self.COOKIES: dict = {}


def _thread(client_row=None):
    from apps.conversations.services import threads as spine_svc

    lead = LeadFactory()
    conversation = ConversationFactory(lead=lead)
    thread = spine_svc.create_thread(visitor_session="sess-team-upload", lead=lead)
    thread.conversation = conversation
    if client_row is not None:
        thread.client = client_row
    thread.save(update_fields=["conversation", "client"] if client_row else ["conversation"])
    return thread


def test_a_team_user_may_attach_to_any_thread():
    """The feature: staff put the NDA into the customer's conversation."""
    from apps.attachments.permissions import staff_may_attach

    assert staff_may_attach(_Req(AdminUserFactory(email="staff-up@itrix.test")), _thread()) is True


def test_a_client_is_never_a_team_caller():
    """
    THE REGRESSION. A signed-in customer must not pass as staff — that would let them
    attach to any thread, including somebody else's.
    """
    from apps.attachments.permissions import is_team_caller, staff_may_attach

    intruder = ClientFactory(email="intruder@customer.test")
    victim_thread = _thread(client_row=ClientFactory(email="victim@customer.test"))

    assert is_team_caller(_Req(intruder)) is False
    assert staff_may_attach(_Req(intruder), victim_thread) is False


def test_an_anonymous_caller_is_never_a_team_caller():
    from django.contrib.auth.models import AnonymousUser

    from apps.attachments.permissions import is_team_caller

    assert is_team_caller(_Req(AnonymousUser())) is False
    assert is_team_caller(_Req(None)) is False


def test_an_inactive_team_user_is_not_a_team_caller():
    from apps.attachments.permissions import is_team_caller

    user = AdminUserFactory(email="retired@itrix.test")
    user.is_active = False
    user.save(update_fields=["is_active"])

    assert is_team_caller(_Req(user)) is False


def test_a_viewer_may_still_send_a_document():
    """
    VIEWER is a team role, and this predicate answers "is this staff", not "may this role
    act". Read-only enforcement lives on the routes that need it (the support and
    attachment decisions carry `IsNotViewer`); putting a role rule here as well would put
    the same decision in two places and let them drift.
    """
    from apps.attachments.permissions import is_team_caller

    assert is_team_caller(_Req(ViewerUserFactory(email="viewer-up@itrix.test"))) is True


def test_staff_attachment_does_not_confer_thread_ownership():
    """
    `staff_may_attach` is deliberately separate from `owns_thread`. Widening the latter
    would have widened `CanDownloadAttachment` with it — and that gate exists precisely so
    that another subject cannot reach a visitor's bytes.
    """
    from apps.attachments.permissions import owns_thread

    assert owns_thread(_Req(AdminUserFactory(email="staff-noown@itrix.test")), _thread()) is False


def test_staff_cannot_download_a_visitors_file_through_the_visitor_endpoint():
    """The consequence of the property above, at the endpoint."""
    from apps.attachments.models import Attachment, AttachmentStatus
    from apps.attachments.permissions import CanDownloadAttachment

    thread = _thread(client_row=ClientFactory(email="owner@customer.test"))
    theirs = Attachment.objects.create(
        thread=thread,
        filename="our-architecture.pdf",
        bytes=64,
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        status=AttachmentStatus.READY,
        uploaded_by_kind=Attachment.UploadedByKind.CLIENT,
    )

    allowed = CanDownloadAttachment().has_object_permission(
        _Req(AdminUserFactory(email="staff-dl@itrix.test")), None, theirs
    )

    assert allowed is False
