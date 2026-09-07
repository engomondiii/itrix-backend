from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_healthz_is_liveness_only():
    res = Client().get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_readyz_is_200_when_database_is_reachable():
    res = Client().get("/readyz")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readyz_is_safe_503_when_database_is_unavailable():
    with patch("itrix.urls.connection.cursor", side_effect=RuntimeError("postgresql://secret@host/db")):
        res = Client().get("/readyz")

    assert res.status_code == 503
    assert res.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    assert b"secret" not in res.content
    assert b"postgresql" not in res.content
