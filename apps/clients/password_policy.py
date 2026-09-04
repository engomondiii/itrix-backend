"""Canonical client password validation.

The client plane is not Django's User model, but it must still use the deployment's
configured Django password validators plus the explicit minimum-length requirement used by
all client entry points. Keeping this in one module prevents invitation/set-password routes
from drifting away from registration/reset/change.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


def min_length() -> int:
    return int(getattr(settings, "PASSWORD_MIN_LENGTH", 12))


def validate_client_password(value: str) -> str:
    value = value or ""
    if len(value) < min_length():
        raise DjangoValidationError(f"Use at least {min_length()} characters.")
    # Reuse AUTH_PASSWORD_VALIDATORS when configured. ``user=None`` intentionally avoids
    # pretending a Client is a Django auth User while still applying password-only checks.
    django_validate_password(value, user=None)
    return value
