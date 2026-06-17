"""itriX Django project package.

In Phases 2–3 the Celery app is autodiscovered here so that `tasks.celery.app`
is importable as `itrix.celery` and shared task decorators work everywhere.

Phase 1 ships with no `tasks/` package yet, so the import is guarded: the project
must boot cleanly whether or not Celery is installed or the tasks package exists.
"""

from __future__ import annotations

try:  # pragma: no cover - exercised only once tasks/ exists (Phase 2+)
    from tasks.celery import app as celery_app

    __all__ = ("celery_app",)
except Exception:  # noqa: BLE001 - any failure must not break Django startup
    celery_app = None
    __all__ = ()
