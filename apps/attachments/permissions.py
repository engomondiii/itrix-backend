"""
Attachment permissions (Backend v6.0 §4.4).

Two gates, and the difference between them is the thread-scoping boundary:

    CanAttachToThread     may this caller add a file to THIS thread?
    CanDownloadAttachment may this caller fetch THESE bytes?

── SCOPED TO THE THREAD, NOT TO THE FILE (§4.6 boundary 3) ──────────────────
An attachment is scoped to its thread. Another subject cannot retrieve it, and no
retrieval path can reach it. Both permissions therefore resolve OWNERSHIP OF THE THREAD
and never trust an id in the URL — a thread id is not a secret, and URL obscurity is
never authorization (§11.9).
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


def _session_from(request) -> str:
    header = request.META.get("HTTP_X_ITRIX_SESSION", "") or ""
    if header.strip():
        return header.strip()[:64]
    return (request.COOKIES.get("itrix_visitor_session", "") or "").strip()[:64]


def owns_thread(request, thread) -> bool:
    """
    Whether this caller owns ``thread``.

    Checked against the SIGNED SESSION or the authenticated client — never against a
    value the caller supplied in the body.
    """
    if thread is None:
        return False

    from apps.clients.models import Client

    user = getattr(request, "user", None)
    if isinstance(user, Client) and user.is_active:
        return thread.client_id == user.id

    session = _session_from(request)
    if not session:
        return False
    return thread.visitor_session == session and thread.client_id is None


class CanAttachToThread(BasePermission):
    message = "You can only attach files to your own conversation."

    def has_permission(self, request, view) -> bool:
        thread = getattr(view, "get_thread", lambda: None)()
        return owns_thread(request, thread)


class CanDownloadAttachment(BasePermission):
    """
    Gates the signed download endpoint.

    A QUARANTINED attachment is never downloadable on the visitor plane, regardless of
    ownership — releasing it requires a deliberate, logged team action.
    """

    message = "This file is not available."

    def has_object_permission(self, request, view, obj) -> bool:
        if obj is None or obj.is_deleted:
            return False
        if not obj.is_downloadable:
            return False
        return owns_thread(request, obj.thread)
