"""Fixtures for the admin smoke tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _admin_test_settings(settings):
    # The admin templates render ``{% static %}`` for every Jazzmin asset. Under
    # WhiteNoise's manifest storage that requires a collectstatic manifest, which
    # a test run does not have — use the plain storage so URLs resolve without one.
    # (Production still runs collectstatic in the Dockerfile; that path is covered
    # separately by ``test_collectstatic_succeeds``.)
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    # Django 5.2's PBKDF2 default is ~1s per hash; ~300 parametrised tests each
    # create a superuser, so use the fast hasher here.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
