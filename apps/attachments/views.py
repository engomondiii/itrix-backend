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
    """
    Mint a visitor session.

    Imported from the thread views rather than re-implemented: the cookie name, the
    length and the retention window have to be the SAME value in both places or a file
    staged here would belong to a session the thread endpoints do not recognise.
    """
    from apps.conversations.views_thread import new_visitor_session as mint

    return mint()


def _set_visitor_session_cookie(response, session_id: str):
    """Attach the visitor-session cookie, with the thread views' own flags."""
    from apps.conversations.views_thread import _set_session_cookie

    return _set_session_cookie(response, session_id)


def _authenticated_client(request):
    """The signed-in Client, or None. Used only to label who staged an upload."""
    from apps.clients.models import Client

    user = getattr(request, "user", None)
    return user if isinstance(user, Client) and user.is_active else None


class AttachmentUploadView(APIView):
    """POST attachments/ — stage one file against a thread the caller owns."""

    # ── CLIENT PLANE (2026-08-10) ─────────────────────────────────────────────
    # owns_thread() has always had a client branch (thread.client_id == user.id),
    # but with no authenticator on these views request.user could never BE a
    # Client, so the workspace could not attach files to its own thread. The
    # authenticator populates request.user when a Bearer client-JWT is present
    # and stays silent otherwise, so the anonymous session path is unchanged.
    permission_classes = [AllowAny]
    # ── TEAM PLANE (2026-08-12) ───────────────────────────────────────────────
    # `JWTAuthentication` is added so a team member can send a file INTO a customer's
    # thread from the console. Order matters only in that each authenticator stays
    # silent when its own credential is absent, so the anonymous session path — no
    # Authorization header at all — is untouched by both.
    authentication_classes = [ClientJWTAuthentication, JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not _flag_enabled():
            return Response({"detail": "Attachments are not enabled."},
                            status=status.HTTP_404_NOT_FOUND)

        upload = request.FILES.get("file")
        thread_id = str(request.data.get("thread_id") or "").strip()
        if upload is None:
            return Response({"detail": "No file supplied."}, status=status.HTTP_400_BAD_REQUEST)

        # ── THE ARRIVAL SCREEN HAS NO THREAD (2026-08-13) ─────────────────────
        # A visitor attaches before typing anything, so `thread_id` is absent and there is
        # no Thread to own. This used to fall through to the `thread is None` branch below
        # and return 404 `{"detail": "Not found."}` — which the composer rendered under the
        # filename as "Not found.", making a working upload look like a missing file.
        #
        # An absent thread_id is therefore NOT the same as an unowned one. It stages the
        # file against the CALLER (session or client) and `intake.bind` moves it onto the
        # thread when the first turn creates one. A thread_id that IS supplied is still
        # checked exactly as before: a wrong or foreign id remains a 404.
        unbound = not thread_id
        issued_session = ""

        if unbound:
            if is_team_caller(request):
                # Staff attach INTO a named conversation. There is no such thing as a team
                # upload with no destination, and allowing one would create a file no
                # thread-scoped query could ever reach.
                return Response(
                    {"detail": "A thread is required to attach a file as a team member."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            thread = None
            by_team = False
            owner_id = uploader_id_for(request)
            if not owner_id:
                # First action on the site was attaching a file. Mint the session now so
                # the upload has an owner, and return it as a cookie so the turn that
                # follows arrives as the same visitor — otherwise the thread would be
                # created under a different session and could never claim this file.
                owner_id = new_visitor_session()
                issued_session = owner_id
            owner_kind = (
                "client" if _authenticated_client(request) is not None else "session"
            )
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
                # The kind is derived from WHO UPLOADED IT, not from who owns the thread.
                # A staff file on a client thread used to be indistinguishable from the
                # client's own upload, which matters twice over: the excerpt selector
                # fences visitor uploads as untrusted input, and the attachment review
                # queue exists to look at what visitors sent us.
                uploaded_by_kind=(
                    owner_kind if unbound
                    else (
                        "team" if by_team and not owns_thread(request, thread)
                        else ("client" if thread.client_id else "session")
                    )
                ),
                uploaded_by_id=str(
                    owner_id if unbound
                    else (
                        getattr(request.user, "id", "")
                        if by_team and not owns_thread(request, thread)
                        else (thread.client_id or thread.visitor_session or "")
                    )
                ),
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
        response = Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
        if issued_session:
            _set_visitor_session_cookie(response, issued_session)
        return response


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
    # See AttachmentUploadView: the client branch of owns_thread needs a user, and the
    # team authenticator lets the console poll the status of a file IT staged (GET only —
    # `delete` refuses team callers below).
    authentication_classes = [ClientJWTAuthentication, JWTAuthentication]

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id, allow_team_own_upload=True)
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
    # See AttachmentUploadView: the client branch of owns_thread needs a user.
    authentication_classes = [ClientJWTAuthentication]

    def get(self, request, attachment_id):
        attachment = _load(request, attachment_id)
        if attachment is None or not attachment.is_downloadable:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not storage.exists(attachment.blob_key):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # An unbound attachment has no thread to read the plane off, so the subject falls
        # back to the uploader it was staged against — which is the same identity, just
        # recorded before the conversation existed.
        thread = attachment.thread
        audit.record_download(
            attachment,
            plane="client" if (thread and thread.client_id) else "anonymous",
            subject=str(
                (thread.client_id or thread.visitor_session)
                if thread
                else attachment.uploaded_by_id
            ),
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


def _load(request, attachment_id, *, allow_team_own_upload: bool = False):
    """
    Load an attachment ONLY if the caller owns its thread.

    ``allow_team_own_upload`` widens this to a team member reading back a file THEY
    staged (``uploaded_by_kind == "team"``) — enough to poll its scan status, and no
    further. It is off by default and passed only from the GET handler, so DELETE stays
    a visitor-only action: staff purging a customer's file belongs behind the audited
    quarantine route in the cockpit, not here.
    """
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
