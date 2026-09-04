"""AI Engine views.

The historical public ``ai/generate-result/`` endpoint is retired.  My Review generation
now starts from the browser-bound review flow and becomes readable only through the
one-time exchange -> server-side access-session path.  Keeping a public endpoint that
accepts a lead/session UUID would make those identifiers act like review credentials and
would bypass the secure-access architecture.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


logger = logging.getLogger("itrix")


class GenerateResultView(APIView):
    """Retired public result generator.

    The team-only generation endpoint lives under ``result-page/generate/``.  Surface 1
    must use ``review/sessions/{id}/result-status/`` and the client-page exchange flow.
    Return one invariant shape without resolving supplied identifiers.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "review_submit"

    def post(self, request):
        return Response(
            {
                "error": {
                    "detail": "This review-generation route has been retired.",
                    "code": "legacy_generation_retired",
                }
            },
            status=status.HTTP_410_GONE,
        )
