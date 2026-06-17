"""Celery tasks package for the itriX backend."""

from __future__ import annotations

try:  # pragma: no cover
    from tasks.celery import app as celery_app

    __all__ = ("celery_app",)
except Exception:  # noqa: BLE001
    celery_app = None
    __all__ = ()
