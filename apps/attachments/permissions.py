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


def is_team_caller(request) -> bool:
    """
    Whether this caller is an authenticated, active iTrix TEAM USER.

    ── WHY THIS DOES NOT REUSE core.permissions._is_active_team_member ──────────
    That predicate is `user and user.is_authenticated and user.is_active` — which is a
    correct team check ONLY on views whose sole authenticator is team SimpleJWT, because
    there `request.user` can only ever be a team User. It is the wrong check HERE:
    this view also runs `ClientJWTAuthentication`, so `request.user` may be a CLIENT,
    and a Client is authenticated and active. Reusing it let any signed-in customer
    pass as staff — and therefore attach a file to ANY thread, including another
    customer's. `test_a_stranger_cannot_stage_a_file_against_someone_elses_thread`
    caught exactly that, which is why it is named here.

    So the type is part of the question, not an assumption: the caller must be an
    instance of the team user model, must not be a Client, and must hold one of the
    team roles. Any future authenticator added to this view is checked against all
    three rather than inheriting a yes.
    """
    from django.contrib.auth import get_user_model

    from apps.clients.models import Client

    user = getattr(request, "user", None)
    if user is None or isinstance(user, Client):
        return False
    if not (getattr(user, "is_authenticated", False) and getattr(user, "is_active", False)):
        return False
    if not isinstance(user, get_user_model()):
        return False
    return str(getattr(user, "role", "")) in set(get_user_model().Role.values)


def staff_may_attach(request, thread) -> bool:
    """
    Whether a team caller may attach a file to ``thread`` (staff → visitor, 2026-08-12).

    ── WHY THIS IS A SEPARATE FUNCTION AND NOT A BRANCH IN owns_thread ─────────
    ``owns_thread`` answers "is this the subject's own conversation?", and every
    download check and every visitor-plane gate is built on that answer. Widening it to
    include staff would silently widen all of them at once — including
    ``CanDownloadAttachment``, where the whole point is that another subject cannot
    reach these bytes.

    So staff attachment is its own predicate, used in exactly one place (the upload
    view), and it does NOT grant staff the download path. A team member sending a
    document to a customer needs to put it there; they do not need to fetch the
    customer's files back through the visitor endpoint.
    """
    if thread is None:
        return False
    return is_team_caller(request)


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
