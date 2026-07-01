"""L4/L5 second-approver rule."""

from __future__ import annotations

import pytest

from apps.governance.models import ApprovalRequest, ApprovalStatus
from apps.governance.services import approval_router
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db


def _l5_request():
    return ApprovalRequest.objects.create(claim_level=5, draft_body="term sheet", status=ApprovalStatus.PENDING)


def test_l5_first_approval_awaits_second():
    req = _l5_request()
    approval_router.approve(req, actor=AdminUserFactory())
    req.refresh_from_db()
    assert req.status == ApprovalStatus.AWAITING_SECOND


def test_l5_same_approver_cannot_complete():
    req = _l5_request()
    u = AdminUserFactory()
    approval_router.approve(req, actor=u)
    with pytest.raises(approval_router.ApprovalError):
        approval_router.approve(req, actor=u)


def test_l5_second_distinct_approver_completes():
    req = _l5_request()
    approval_router.approve(req, actor=AdminUserFactory())
    approval_router.approve(req, actor=AdminUserFactory())
    req.refresh_from_db()
    assert req.status == ApprovalStatus.APPROVED


def test_l3_completes_on_first_approval():
    req = ApprovalRequest.objects.create(claim_level=3, draft_body="draft", status=ApprovalStatus.PENDING)
    approval_router.approve(req, actor=AdminUserFactory())
    req.refresh_from_db()
    assert req.status == ApprovalStatus.APPROVED


def test_resolved_request_cannot_be_reapproved():
    req = ApprovalRequest.objects.create(claim_level=3, draft_body="d", status=ApprovalStatus.PENDING)
    approval_router.approve(req, actor=AdminUserFactory())
    with pytest.raises(approval_router.ApprovalError):
        approval_router.approve(req, actor=AdminUserFactory())
