"""
Attachment views (Backend v6.0 §7.1).

    POST   attachments/                    stage an upload
    GET    attachments/{id}/               status + metadata
    GET    attachments/{id}/download/      signed, authorized, disposition=attachment
    DELETE attachments/{id}/               visitor-initiated purge

── THE DOWNLOAD ENDPOINT IS THE WHOLE SECURITY STORY (§4.4) ─────────────────
Blobs are never on a public path. Every fetch goes through here, which:
    * re-checks ownership on EVERY request (URL obscurity is never authorization)
    * refuses a quarantined file outright
    * sets Content-Disposition: attachment so nothing renders inline
    * sets a restrictive CSP and nosniff so a mislabelled HTML file cannot execute
    * writes an audit row
"""

from __future__ import annotations

import logging

from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.attachments import policy, storage
from apps.attachments.models import Attachment
from apps.attachments.permissions import owns_thread
from apps.attachments.serializers import AttachmentSerializer
from apps.attachments.services import audit, intake, retention

logger = logging.getLogger("itrix")


def _flag_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "ENABLE_ATTACHMENTS", False))


class AttachmentUploadView(APIView):
    """POST attachments/ — stage one file against a thread the caller owns."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not _flag_enabled():
            return Response({"detail": "Attachments are not enabled."},
                            status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("file")
        thread_id = request.data.get("thread_id") or ""
        if upload is None:
            return Response({"detail": "No file supplied."}, status=status.HTTP_400_BAD_REQUEST)

        thread = _load_thread(thread_id)
        if thread is None or not owns_thread(request, thread):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        data = upload.read()
        try:
            attachment = intake.stage(
                thread=thread,
                filename=upload.name,
                data=data,
                declared_mime=getattr(upload, "content_type", "") or "",
                uploaded_by_kind="client" if thread.client_id else "session",
                uploaded_by_id=str(thread.client_id or thread.visitor_session or ""),
            )
        except intake.AttachmentRejected as exc:
            # A rejected FILE never rejects the TURN. The message tells them what they
            # can still do.
            return Response(
                {"detail": exc.message, "reason": exc.reason},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        _process(attachment)
        attachment.refresh_from_db()
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


def _process(attachment) -> None:
    """Run scan -> extract. Async when Celery is on, inline otherwise."""
    from django.conf import settings

    if getattr(settings, "ENABLE_CELERY", False):
        try:
            from tasks.attachment_tasks import process_attachment

            process_attachment.delay(str(attachment.id))
            return
        except Exception:  # noqa: BLE001
            logger.debug("celery dispatch failed; processing inline")
    try:
        intake.process(attachment)
    except Exception:  # noqa: BLE001
        logger.exception("inline attachment processing failed for %s", attachment.id)


class AttachmentDetailView(APIView):
    """GET / DELETE attachments/{id}/."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id)
        if attachment is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AttachmentSerializer(attachment).data)

    def delete(self, request, attachment_id):
        """
        Visitor-initiated delete (§19.7 rule 8).

        Purges immediately rather than scheduling: "we have deleted this file and
        anything we read from it" must be true when it is said.
        """
        attachment = _load(request, attachment_id)
        if attachment is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        report = retention.visitor_delete(attachment)
        return Response(
            {"detail": policy.MSG_DELETED, "verified": report.get("blob_removed", False)},
            status=status.HTTP_200_OK,
        )


class AttachmentDownloadView(APIView):
    """GET attachments/{id}/download/ — signed, authorized, never inline."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id)
        if attachment is None or not attachment.is_downloadable:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not storage.exists(attachment.blob_key):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        audit.record_download(
            attachment,
            plane="client" if attachment.thread.client_id else "anonymous",
            subject=str(attachment.thread.client_id or attachment.thread.visitor_session),
            purpose="visitor download",
        )

        response = FileResponse(
            open(storage.blob_root() / attachment.blob_key, "rb"),
            content_type="application/octet-stream",
        )
        _harden(response, attachment.filename)
        return response


def _safe_filename(filename: str) -> str:
    """
    Reduce an attacker-controlled filename to something safe in a header.

    A filename arrives from the upload and is therefore hostile input. Stripping CR and
    LF alone is not enough: the RESIDUE of an injection attempt
    ("evil.txt" + "X-Injected: yes") still lands inside the header VALUE, where it is
    harmless but misleading to anyone reading logs or a proxy trace.

    So this is an ALLOW-LIST, not a strip-list. Only characters that legitimately appear
    in a filename survive; everything else — control characters, quotes, colons,
    semicolons, backslashes — is replaced with an underscore.
    """
    import re

    raw = (filename or "").strip() or "file"
    # Drop any directory component first: "../../etc/passwd" is a filename.
    raw = raw.replace("\\", "/").split("/")[-1]
    # Allow-list: letters, digits, space, dot, dash, underscore, parentheses.
    cleaned = re.sub(r"[^A-Za-z0-9 ._()\-]", "_", raw)
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(" ._") or "file"
    return cleaned[:120]


def _harden(response: HttpResponse, filename: str) -> HttpResponse:
    """
    The headers that stop an upload from becoming an execution.

    ``Content-Disposition: attachment`` means the browser downloads rather than renders.
    ``nosniff`` stops it second-guessing the type. The CSP is a sandbox for the case
    where something renders it anyway.
    """
    response["Content-Disposition"] = f'attachment; filename="{_safe_filename(filename)}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["X-Frame-Options"] = "DENY"
    response["Cache-Control"] = "private, no-store"
    return response


def _load_thread(thread_id: str):
    from apps.conversations.models import Thread

    try:
        return Thread.objects.filter(id=thread_id).select_related("client").first()
    except Exception:  # noqa: BLE001
        return None


def _load(request, attachment_id):
    """Load an attachment ONLY if the caller owns its thread."""
    try:
        attachment = (
            Attachment.objects.filter(id=attachment_id)
            .select_related("thread", "thread__client")
            .first()
        )
    except Exception:  # noqa: BLE001
        return None
    if attachment is None or attachment.is_deleted:
        return None
    if not owns_thread(request, attachment.thread):
        return None
    return attachment
