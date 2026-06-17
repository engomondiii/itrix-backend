"""
Response helpers.

Small builders so views and services produce consistent success/error payloads.
Success responses stay un-enveloped (bare DTOs) to match the frontends; the error
helper produces the same ``{error:{detail,...}}`` shape as the exception handler.
"""

from __future__ import annotations

from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response


def ok(data: Any = None, *, status: int = http_status.HTTP_200_OK) -> Response:
    """Return a success response with the data passed straight through."""
    return Response(data if data is not None else {}, status=status)


def created(data: Any = None) -> Response:
    return Response(data if data is not None else {}, status=http_status.HTTP_201_CREATED)


def no_content() -> Response:
    return Response(status=http_status.HTTP_204_NO_CONTENT)


def error(
    detail: str,
    *,
    code: str = "error",
    status: int = http_status.HTTP_400_BAD_REQUEST,
    fields: dict | None = None,
) -> Response:
    """Return an error response in the canonical envelope."""
    body: dict[str, Any] = {"error": {"detail": detail, "code": code}}
    if fields:
        body["error"]["fields"] = fields
    return Response(body, status=status)
