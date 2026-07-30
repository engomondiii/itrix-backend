"""
Cockpit row-level views (Backend v7.1 §Phase 1) — TEAM PLANE ONLY.

    GET cockpit/threads/                    the conversation board
    GET cockpit/threads/{id}/               one conversation + internal overlay
    GET cockpit/customers/                  the customer health board
    GET cockpit/customers/{id}/             one customer's health
    GET cockpit/streaming/guard-hits/       governance halts, as rows

    v7.1 PHASE 2 adds:
    GET  cockpit/threads/{id}/coverage/     the ten listening dimensions + evidence
    GET  cockpit/support/queue/             the support queue, blocking first
    GET  cockpit/support/queue/{id}/        one request, with the customer's own words
    GET  cockpit/attachments/               files waiting on a human, oldest first
    GET  cockpit/attachments/{id}/          one file, its scans and its audit trail
    POST cockpit/attachments/{id}/release/    REQUIRES A WRITTEN REASON
    POST cockpit/attachments/{id}/quarantine/ REQUIRES A WRITTEN REASON

── WHAT THESE ROUTES ARE, AND WHY THEIR NAMES WERE TAKEN ───────────────────
v6.0 mounted four ANALYTICS views at ``cockpit/``, so ``cockpit/threads/`` returned
thread metrics while the dashboard was asking for a thread list. The dashboard's 501
guards were read as "the backend has not built this yet" when the truth was that the name
was occupied by an aggregate.

v7.1 Phase 1 frees the names — the aggregates keep their homes under ``analytics/``, where
they were already mounted — and gives them to these resources. The rule, stated once:

    AGGREGATES under analytics/        distributions, counts, trends
    ROW-LEVEL RESOURCES under cockpit/  individual threads, customers, files, halts

── EVERY ROUTE HERE READS §10.5 INTERNAL-ONLY MATERIAL ─────────────────────
Governance status, claim levels, cited chunk ids, health classes, halts. None of it is
reachable on the anonymous or client plane at any state, which is why all of it is behind
``IsDashboardUser`` and mounted nowhere else.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cockpit.permissions import may_see_matched_text
from apps.cockpit.services import attachment_review as attachment_svc
from apps.cockpit.services import coverage as coverage_svc
from apps.cockpit.services import customers as customers_svc
from apps.cockpit.services import guard_hits as guard_hits_svc
from apps.cockpit.services import support_queue as support_svc
from apps.cockpit.services import threads as threads_svc
from apps.cockpit.services.attachment_review import ReleaseRefused
from apps.core.permissions import IsDashboardUser, IsNotViewer

logger = logging.getLogger("itrix")


def _int_param(request, name: str, default: int) -> int:
    """A query parameter that cannot become a 500. Junk resolves to the default."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class _CockpitView(APIView):
    """Team plane, always. Never mounted anywhere but ``cockpit/``."""

    permission_classes = [IsAuthenticated, IsDashboardUser]


class CockpitThreadBoardView(_CockpitView):
    """
    GET cockpit/threads/ — the conversation board.

    ANONYMOUS THREADS ARE INCLUDED AND LABELLED (Surface 2 v7.0 §06). A board that showed
    only threads with a Lead would hide the first-visit conversations, which are exactly
    the ones where a governance halt or a badly-chosen question does the most damage.
    """

    def get(self, request):
        rows = threads_svc.rows(
            limit=_int_param(request, "limit", threads_svc.DEFAULT_LIMIT),
        )
        return Response({"results": rows, "count": len(rows)}, status=status.HTTP_200_OK)


class CockpitThreadDetailView(_CockpitView):
    """
    GET cockpit/threads/{id}/ — one conversation, with its internal overlay.

    The role check happens HERE and the answer is passed into the service. The service does
    not read the request, so it cannot be called from a context with no request and left
    guessing (see services/threads.py).
    """

    def get(self, request, thread_id):
        payload = threads_svc.detail(
            str(thread_id),
            may_see_matched_text=may_see_matched_text(request.user),
        )
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)


class CockpitCustomerBoardView(_CockpitView):
    """
    GET cockpit/customers/ — the customer health board, worst first.

    ``results`` (was ``board``), ``company`` (was ``organization``), ``healthClass``
    (was ``health``) — with four values including ``critical``, and ``reasons`` and
    ``expansionAllowed`` preserved. See services/customers.py for why each rename.
    """

    def get(self, request):
        rows = customers_svc.results(
            limit=_int_param(request, "limit", customers_svc.DEFAULT_LIMIT)
        )
        return Response(
            {
                "results": rows,
                "count": len(rows),
                # Named in the payload so a chart cannot invent a fifth class or collapse
                # `critical` into `at_risk` on its own.
                "healthClasses": list(customers_svc.HEALTH_CLASSES),
            },
            status=status.HTTP_200_OK,
        )


class CockpitCustomerDetailView(_CockpitView):
    """GET cockpit/customers/{id}/ — one customer's health and the reasons behind it."""

    def get(self, request, client_id):
        payload = customers_svc.detail(str(client_id))
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)


class CockpitGuardHitsView(_CockpitView):
    """
    GET cockpit/streaming/guard-hits/ — governance halts, as rows.

    ``matchedText`` is present for ADMIN and ASSESSMENT and ABSENT for everyone else — not
    empty. An empty string reads as "nothing was matched", which is false and would make a
    VIEWER think the halt was spurious.

    The response states which it did, so the dashboard can label the column honestly rather
    than inferring from a missing key.
    """

    def get(self, request):
        allowed = may_see_matched_text(request.user)
        rows = guard_hits_svc.rows(
            limit=_int_param(request, "limit", guard_hits_svc.DEFAULT_LIMIT),
            may_see_matched_text=allowed,
            thread_id=request.query_params.get("threadId") or None,
            category=request.query_params.get("category") or None,
        )
        return Response(
            {
                "results": rows,
                "count": len(rows),
                "matchedTextVisible": allowed,
                # §6.4, restated at the point of use: a rising halt rate is drift, not
                # noise. An operator reading a list of halts should not conclude the guard
                # is doing well.
                "interpretation": (
                    "A halt means a model tried to say something it should not have been "
                    "in a position to say. Treat a rising rate as retrieval or prompt "
                    "drift, not as noise."
                ),
            },
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────────────────────────────────────
# v7.1 PHASE 2
# ─────────────────────────────────────────────────────────────────────────────
class CockpitThreadCoverageView(_CockpitView):
    """
    GET cockpit/threads/{id}/coverage/ — the ten listening dimensions.

    Every row carries its EVIDENCE MESSAGE. "Why is this covered?" must have an answer, or
    the map is a number an operator learns to ignore — the same failure mode as a health
    class without reasons.
    """

    def get(self, request, thread_id):
        payload = coverage_svc.for_thread(str(thread_id))
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)


class CockpitSupportQueueView(_CockpitView):
    """
    GET cockpit/support/queue/ — the support queue. BLOCKING FIRST.

    This endpoint is what makes the customer-first rule LEGIBLE. §18.7 suppresses every
    commercial action while a blocking request is open; an operator who cannot see those
    requests experiences the suppression as obstruction and goes looking for the override.

    So each row says whether it is currently suppressing expansion for its customer. The
    operator meets the reason before the consequence.
    """

    def get(self, request):
        rows = support_svc.rows(
            limit=_int_param(request, "limit", support_svc.DEFAULT_LIMIT),
            include_resolved=request.query_params.get("includeResolved") == "true",
            client_id=request.query_params.get("clientId") or None,
            blocking_only=request.query_params.get("blockingOnly") == "true",
        )
        return Response(
            {"results": rows, "count": len(rows), "summary": support_svc.summary()},
            status=status.HTTP_200_OK,
        )


class CockpitSupportRequestView(_CockpitView):
    """
    GET cockpit/support/queue/{id}/ — one request, with the customer's own words.

    The body is not summarised, truncated or re-worded. An operator working a problem needs
    what was actually said; a summary is where the detail that mattered gets lost.
    """

    def get(self, request, request_id):
        payload = support_svc.detail(str(request_id))
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)


class CockpitAttachmentQueueView(_CockpitView):
    """
    GET cockpit/attachments/ — files waiting on a human. OLDEST FIRST.

    Oldest first, unlike every other queue here. A quarantined attachment is a visitor's
    document in limbo: they uploaded it, the surface said it was being checked, and nothing
    has happened since. Newest-first would leave the oldest waiting indefinitely, and that
    is the outcome the visitor experiences directly.

    This name was an AGGREGATE in v6.0 (attachment metrics). Phase 1 freed it; this is what
    it was freed for.
    """

    def get(self, request):
        rows = attachment_svc.rows(
            limit=_int_param(request, "limit", attachment_svc.DEFAULT_LIMIT),
            include_resolved=request.query_params.get("includeResolved") == "true",
        )
        return Response(
            {"results": rows, "count": len(rows), "summary": attachment_svc.summary()},
            status=status.HTTP_200_OK,
        )


class CockpitAttachmentDetailView(_CockpitView):
    """GET cockpit/attachments/{id}/ — one file, its scan history and its audit trail."""

    def get(self, request, attachment_id):
        payload = attachment_svc.detail(str(attachment_id))
        if payload is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)


class _AttachmentDecisionView(_CockpitView):
    """
    Shared base for release and quarantine.

    ── VIEWER CANNOT DO EITHER ─────────────────────────────────────────────
    ``IsNotViewer`` is added on top of the team gate. A read-only role releasing a file the
    scanner objected to would make "read-only" meaningless in the one place it matters most.
    """

    permission_classes = [IsAuthenticated, IsDashboardUser, IsNotViewer]

    @staticmethod
    def _reason(request) -> str:
        return str((request.data or {}).get("reason") or "")


class CockpitAttachmentReleaseView(_AttachmentDecisionView):
    """
    POST cockpit/attachments/{id}/release/ — release a quarantined file. NEEDS A REASON.

    The reason is enforced at the API, not the UI. A UI-only requirement disappears the
    moment anyone calls the endpoint directly — and the entire value of the reason is that
    it exists LATER, when someone asks why a file the scanner objected to was processed.

    A refusal returns 400 with the reason WHY it was refused, so the operator can supply
    what is missing rather than guessing.
    """

    def post(self, request, attachment_id):
        try:
            result = attachment_svc.release(
                str(attachment_id), user=request.user, reason=self._reason(request)
            )
        except ReleaseRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


class CockpitAttachmentQuarantineView(_AttachmentDecisionView):
    """
    POST cockpit/attachments/{id}/quarantine/ — withhold a file. NEEDS A REASON.

    The inverse of release, and it needs a reason for the same kind of reason: an operator
    quarantining a customer's document is withholding something the customer sent, and the
    customer may ask why.

    Tightening is always permitted, from any state — a file already extracted can still be
    quarantined if a human notices what the scanner did not.
    """

    def post(self, request, attachment_id):
        try:
            result = attachment_svc.quarantine(
                str(attachment_id), user=request.user, reason=self._reason(request)
            )
        except ReleaseRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)
