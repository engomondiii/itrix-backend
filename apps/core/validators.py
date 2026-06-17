"""
Reusable validators and field-level sanitisers.

These are shared by serializers across apps so that, for example, the public review
prompt and the lead-capture email are validated identically everywhere.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

# A lenient but real email check (DRF/Django EmailValidator under the hood).
_email_validator = EmailValidator(message="Enter a valid email address.")

# Visitor prompts: keep them bounded so storage/AI cost stays sane.
MAX_PROMPT_LENGTH = 4000
MIN_PROMPT_LENGTH = 2

# Control characters except common whitespace.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_email_address(value: str) -> str:
    """Validate and normalise an email address (trims + lowercases the domain)."""
    if not value or not value.strip():
        raise ValidationError("Email address is required.")
    value = value.strip()
    _email_validator(value)
    local, _, domain = value.rpartition("@")
    return f"{local}@{domain.lower()}"


def clean_text(value: str | None, *, max_length: int | None = None) -> str:
    """Strip control chars and surrounding whitespace; optionally bound length."""
    if value is None:
        return ""
    value = _CONTROL_CHARS.sub("", str(value)).strip()
    if max_length is not None and len(value) > max_length:
        value = value[:max_length].rstrip()
    return value


def validate_prompt(value: str) -> str:
    """Validate a visitor's compute-bottleneck prompt."""
    cleaned = clean_text(value, max_length=MAX_PROMPT_LENGTH)
    if len(cleaned) < MIN_PROMPT_LENGTH:
        raise ValidationError("Please describe your compute bottleneck.")
    return cleaned


def validate_non_empty(value: str, *, field: str = "value") -> str:
    cleaned = clean_text(value)
    if not cleaned:
        raise ValidationError(f"{field} must not be empty.")
    return cleaned
