"""
Legal routes (Backend v7.1 §15.1).

    GET  legal/instruments/       PUBLIC. Slugs, versions, effective dates.
    POST portal/legal/assent/     CLIENT. Records assent for an authenticated Client.

── THE PUBLIC ENDPOINT SERVES NO TEXT AND NAMES NOBODY ─────────────────────
Versions and dates only. It cannot be used to discover whether an address is registered,
whether a customer exists, or anything else about anyone — it describes the platform, not
its users.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.legal.constants import ASSENT_REQUIRED_SLUGS
from apps.legal.serializers import AssentReceiptSerializer, AssentRequestSerializer
from apps.legal.services import assent as assent_svc
from apps.legal.services import instruments as instruments_svc

logger = logging.getLogger("itrix")


def _client_ip(request) -> str | None:
    """
    The caller's address, from the proxy header when present.

    Best-effort and never fatal. An assent record with no IP is still evidence; an exception
    while resolving one would lose the whole record.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


class LegalInstrumentsView(APIView):
    """
    GET legal/instruments/ — PUBLIC.

    ``published`` is in the payload so `itrix-web` can render the draft banner without a
    second flag of its own. Until counsel signs off, the instruments are still SERVED — a
    visitor must always be able to read what governs their use — but they are not presented
    as authoritative.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response(
            {
                "instruments": instruments_svc.all_instruments(),
                "published": instruments_svc.published(),
                # Named so a client cannot decide for itself which instruments a checkbox
                # should bind. The two lists drifting would make the record claim more than
                # the visitor was shown.
                "assentRequired": list(ASSENT_REQUIRED_SLUGS),
            },
            status=status.HTTP_200_OK,
        )


class PortalAssentView(APIView):
    """
    POST portal/legal/assent/ — CLIENT plane.

    ── THIS IS THE RE-PROMPT PATH, NOT THE PRIMARY ONE ─────────────────────
    The primary path records assent INSIDE the transaction that creates the Client
    (``apps.clients.services.invite.claim_invite``), because a Client must never exist
    without one. By the time a request reaches here, the Client already exists.

    So this endpoint serves the case §19.10 describes separately: a MATERIAL VERSION CHANGE,
    re-prompted at next sign-in. It is also what `itrix-web`'s `legalApi.record` calls during
    the deployment window before the transactional path is live.

    It wraps its own atomic block, because ``record_in_transaction`` refuses to run outside
    one — the guarantee is that the record and its subject land together, and here the
    subject already landed.
    """

    def post(self, request):
        from django.db import transaction

        serializer = AssentRequestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        client = getattr(request, "client", None) or getattr(request.user, "client", None)
        if client is None:
            return Response(
                {"detail": "A client session is required to record assent."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        self._warn_on_version_mismatch(data.get("instruments") or [])

        try:
            with transaction.atomic():
                record = assent_svc.record_in_transaction(
                    client=client,
                    email=getattr(client, "email", "") or "",
                    path="reprompt",
                    accepted_at_client=data.get("acceptedAt"),
                    ip_address=_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
        except assent_svc.AssentRefused as exc:
            # FORWARDED, not degraded. Every other proxy on this platform fails soft so a
            # visitor sees less than they were entitled to; this one fails loud, because an
            # account whose assent was not recorded is the state §19.10 exists to prevent and
            # it cannot be repaired afterwards by guessing what they read.
            logger.error("legal.assent_refused client=%s detail=%s", getattr(client, "id", "?"), exc)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            AssentReceiptSerializer(
                {
                    "recorded": True,
                    "acceptedAt": record.created_at,
                    # The versions ACTUALLY STORED, so a client that sent stale ones can see
                    # the difference in the response.
                    "instruments": record.instruments,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _warn_on_version_mismatch(claimed) -> None:
        """
        Log loudly when the client showed different versions from the ones in force.

        Not an error: the record stores the SERVER's versions, so the write is still correct.
        But it means the visitor read something other than what binds them, and that is worth
        being noisy about rather than silently reconciling.
        """
        for entry in claimed:
            slug = entry.get("slug")
            shown = (entry.get("version") or "").strip()
            current = instruments_svc.version_of(slug)
            if shown and current and shown != current:
                logger.error(
                    "legal.version_mismatch slug=%s client_showed=%s server_has=%s — the "
                    "visitor accepted a version that is not the one in force. Reconcile "
                    "itrix-web lib/content/legalCopy.ts with LEGAL_*_VERSION.",
                    slug, shown, current,
                )
