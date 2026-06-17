"""
Exception handling.

Custom DRF exceptions plus a handler that normalises every error response to a
single envelope the frontends already expect::

    { "error": { "detail": "...", "code": "...", "fields": {...} } }

The web proxies look for ``error.detail`` (e.g. ``review/qualify`` falls back to a
local estimate on any non-OK body), so keeping ``detail`` present and human-readable
matters for graceful degradation.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("itrix")


# ── Domain exceptions ────────────────────────────────────────────────────────
class ITrixError(APIException):
    """Base class for itriX domain errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A processing error occurred."
    default_code = "itrix_error"


class ServiceUnavailable(ITrixError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "A required service is temporarily unavailable."
    default_code = "service_unavailable"


class FeatureDisabled(ITrixError):
    """Raised when a feature-flagged capability is called while disabled.

    Note: most flagged services *degrade gracefully* (return stubs) rather than
    raise — this exists for the cases where a hard failure is the right answer.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "This capability is currently disabled."
    default_code = "feature_disabled"


class ResourceConflict(ITrixError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


class InvalidCredentials(APIException):
    """401 for failed logins.

    Raised explicitly (rather than DRF's ``AuthenticationFailed``, which becomes a
    403 on views that declare no authentication classes) so the dashboard's Next
    proxy receives a true 401 on a bad email/password.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "Invalid email or password."
    default_code = "invalid_credentials"


def itrix_exception_handler(exc, context):
    """Wrap DRF's default handler, normalising the body to the error envelope."""
    response = drf_exception_handler(exc, context)

    if response is None:
        # Unhandled exception — log it and return a clean 500 (never a stack trace).
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            {"error": {"detail": "Internal server error.", "code": "server_error"}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    code = getattr(exc, "default_code", None) or "error"
    fields: dict | None = None
    message: str

    if isinstance(detail, dict):
        if "detail" in detail and len(detail) == 1:
            message = str(detail["detail"])
        else:
            # Serializer/field errors → keep them under `fields`.
            fields = detail
            message = "Validation failed."
    elif isinstance(detail, list):
        message = "; ".join(str(item) for item in detail)
    else:
        message = str(detail)

    envelope = {"error": {"detail": message, "code": code}}
    if fields:
        envelope["error"]["fields"] = fields

    response.data = envelope
    return response
