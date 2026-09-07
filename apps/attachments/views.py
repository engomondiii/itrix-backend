"""Attachment HTTP views. Private bytes are never exposed by a storage URL."""

from __future__ import annotations

import logging

from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.attachments import policy, storage
from apps.attachments.models import Attachment
from apps.clients.backends import ClientJWTAuthentication
from apps.attachments.permissions import (
    is_team_caller,
    owns_attachment,
    owns_thread,
    staff_may_attach,
    uploader_id_for,
)
from apps.attachments.serializers import AttachmentSerializer
from apps.attachments.services import audit, intake, retention

logger = logging.getLogger("itrix")


def _flag_enabled() -> bool:
    from django.conf import settings
    return bool(getattr(settings, "ENABLE_ATTACHMENTS", False))


def new_visitor_session() -> str:
    from apps.conversations.views_thread import new_visitor_session as mint
    return mint()


def _set_visitor_session_cookie(response, session_id: str):
    from apps.conversations.views_thread import _set_session_cookie
    return _set_session_cookie(response, session_id)


def _authenticated_client(request):
    from apps.clients.models import Client
    user = getattr(request, "user", None)
    return user if isinstance(user, Client) and user.is_active else None


class AttachmentUploadView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication, JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not _flag_enabled():
            return Response(
                {"detail": "Attachments are not enabled."}, status=status.HTTP_404_NOT_FOUND
            )
        upload = request.FILES.get("file")
        thread_id = str(request.data.get("thread_id") or "").strip()
        if upload is None:
            return Response({"detail": "No file supplied."}, status=status.HTTP_400_BAD_REQUEST)

        unbound = not thread_id
        issued_session = ""
        if unbound:
            if is_team_caller(request):
                return Response(
                    {"detail": "A thread is required to attach a file as a team member."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            thread = None
            by_team = False
            owner_id = uploader_id_for(request)
            if not owner_id:
                owner_id = new_visitor_session()
                issued_session = owner_id
            owner_kind = "client" if _authenticated_client(request) is not None else "session"
        else:
            thread = _load_thread(thread_id)
            by_team = staff_may_attach(request, thread)
            if thread is None or not (owns_thread(request, thread) or by_team):
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            owner_kind = ""
            owner_id = ""

        data = upload.read()
        try:
            attachment = intake.stage(
                thread=thread,
                filename=upload.name,
                data=data,
                declared_mime=getattr(upload, "content_type", "") or "",
                uploaded_by_kind=(
                    owner_kind
                    if unbound
                    else (
                        "team"
                        if by_team and not owns_thread(request, thread)
                        else ("client" if thread.client_id else "session")
                    )
                ),
                uploaded_by_id=str(
                    owner_id
                    if unbound
                    else (
                        getattr(request.user, "id", "")
                        if by_team and not owns_thread(request, thread)
                        else (thread.client_id or thread.visitor_session or "")
                    )
                ),
            )
        except intake.AttachmentRejected as exc:
            return Response(
                {"detail": exc.message, "reason": exc.reason},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        _process(attachment)
        attachment.refresh_from_db()
        response = Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
        if issued_session:
            _set_visitor_session_cookie(response, issued_session)
        return response


def _process(attachment) -> None:
    from django.conf import settings

    process_inline = getattr(settings, "ATTACHMENT_PROCESS_INLINE", True)
    if getattr(settings, "ENABLE_CELERY", False) and not process_inline:
        try:
            from tasks.attachment_tasks import process_attachment
            process_attachment.delay(str(attachment.id))
            return
        except Exception:  # noqa: BLE001
            logger.warning(
                "attachment celery dispatch failed; processing inline for %s",
                attachment.id,
                exc_info=True,
            )
    try:
        intake.process(attachment)
    except Exception:  # noqa: BLE001
        logger.exception("inline attachment processing failed for %s", attachment.id)


class AttachmentDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication, JWTAuthentication]

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id, allow_team_own_upload=True)
        if attachment is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AttachmentSerializer(attachment).data)

    def delete(self, request, attachment_id):
        attachment = _load(request, attachment_id)
        if attachment is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        report = retention.visitor_delete(attachment)
        return Response(
            {"detail": policy.MSG_DELETED, "verified": report.get("blob_removed", False)},
            status=status.HTTP_200_OK,
        )


class AttachmentDownloadView(APIView):
    """Authorize and quarantine-check first, then stream canonical private bytes."""

    permission_classes = [AllowAny]
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id)
        if attachment is None or not attachment.is_downloadable:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Head/exists happens only after authorization and the quarantine/downloadability gate.
        try:
            available = storage.exists(attachment.blob_key)
        except Exception:  # noqa: BLE001
            logger.exception("attachment storage availability check failed for %s", attachment.id)
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not available:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        thread = attachment.thread
        audit.record_download(
            attachment,
            plane="client" if (thread and thread.client_id) else "anonymous",
            subject=str(
                (thread.client_id or thread.visitor_session) if thread else attachment.uploaded_by_id
            ),
            purpose="visitor download",
        )
        response = StreamingHttpResponse(
            storage.iter_chunks(attachment.blob_key),
            content_type="application/octet-stream",
        )
        _harden(response, attachment.filename)
        return response


def _safe_filename(filename: str) -> str:
    import re

    raw = (filename or "").strip() or "file"
    raw = raw.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r"[^A-Za-z0-9 ._()\-]", "_", raw)
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(" ._") or "file"
    return cleaned[:120]


def _harden(response: HttpResponse, filename: str) -> HttpResponse:
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


def _load(request, attachment_id, *, allow_team_own_upload: bool = False):
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
    if owns_attachment(request, attachment):
        return attachment
    if (
        allow_team_own_upload
        and attachment.uploaded_by_kind == Attachment.UploadedByKind.TEAM
        and is_team_caller(request)
    ):
        return attachment
    return None
