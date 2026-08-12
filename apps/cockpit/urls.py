"""
Cockpit row-level routes, mounted at /api/v1/cockpit/ — TEAM PLANE ONLY.

Order matters: the ``streaming/guard-hits/`` and ``{id}/`` sub-resources are declared
BEFORE any bare collection route that could swallow them.

The existing ``cockpit/leads/*`` routes stay in api/v1/urls.py. They are row-level already
and were never part of the naming confusion this phase resolves.
"""

from __future__ import annotations

from django.urls import path

from apps.cockpit.views import (
    CockpitAttachmentDetailView,
    CockpitAttachmentQuarantineView,
    CockpitAttachmentQueueView,
    CockpitAttachmentReleaseView,
    CockpitCustomerBoardView,
    CockpitCustomerDetailView,
    CockpitGuardHitsView,
    CockpitSupportAssignView,
    CockpitSupportQueueView,
    CockpitSupportRequestView,
    CockpitSupportResolveView,
    CockpitThreadBoardView,
    CockpitThreadCoverageView,
    CockpitThreadDetailView,
)

app_name = "cockpit_resources"

urlpatterns = [
    # ── Conversations ────────────────────────────────────────────────────────
    # The coverage sub-resource is declared BEFORE the bare {id}/ route, which would
    # otherwise swallow it.
    path("threads/<uuid:thread_id>/coverage/", CockpitThreadCoverageView.as_view(), name="thread-coverage"),
    path("threads/<uuid:thread_id>/", CockpitThreadDetailView.as_view(), name="thread-detail"),
    path("threads/", CockpitThreadBoardView.as_view(), name="thread-board"),
    # ── Customers ────────────────────────────────────────────────────────────
    path("customers/<uuid:client_id>/", CockpitCustomerDetailView.as_view(), name="customer-detail"),
    path("customers/", CockpitCustomerBoardView.as_view(), name="customer-board"),
    # ── Support (v7.1 Phase 2; actions 2026-08-12) ───────────────────────────
    # Action routes before the bare {id}/, which would otherwise swallow them — the same
    # ordering rule as the attachment routes below.
    path("support/queue/<uuid:request_id>/assign/", CockpitSupportAssignView.as_view(), name="support-assign"),
    path("support/queue/<uuid:request_id>/resolve/", CockpitSupportResolveView.as_view(), name="support-resolve"),
    path("support/queue/<uuid:request_id>/", CockpitSupportRequestView.as_view(), name="support-request"),
    path("support/queue/", CockpitSupportQueueView.as_view(), name="support-queue"),
    # ── Attachment review (v7.1 Phase 2) ─────────────────────────────────────
    # The action routes come first; a bare {id}/ would swallow them.
    path("attachments/<uuid:attachment_id>/release/", CockpitAttachmentReleaseView.as_view(), name="attachment-release"),
    path("attachments/<uuid:attachment_id>/quarantine/", CockpitAttachmentQuarantineView.as_view(), name="attachment-quarantine"),
    path("attachments/<uuid:attachment_id>/", CockpitAttachmentDetailView.as_view(), name="attachment-detail"),
    path("attachments/", CockpitAttachmentQueueView.as_view(), name="attachment-queue"),
    # ── Governance halts ─────────────────────────────────────────────────────
    # Under `streaming/` rather than at the top level, because the aggregate that answers
    # "is this rising?" lives at analytics/streaming/ and the two belong to one subject.
    path("streaming/guard-hits/", CockpitGuardHitsView.as_view(), name="guard-hits"),
]
