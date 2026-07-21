"""Attachment routes (mounted at /api/v1/attachments/) — session/client scoped."""

from __future__ import annotations

from django.urls import path

from apps.attachments.views import (
    AttachmentDetailView,
    AttachmentDownloadView,
    AttachmentUploadView,
)

app_name = "attachments"

urlpatterns = [
    path("", AttachmentUploadView.as_view(), name="attachment-upload"),
    path("<uuid:attachment_id>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
    path("<uuid:attachment_id>/", AttachmentDetailView.as_view(), name="attachment-detail"),
]
