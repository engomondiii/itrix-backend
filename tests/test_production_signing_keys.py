from __future__ import annotations

import os
import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

from itrix.settings.security_validation import validate_production_signing_keys


STRONG_TEAM_KEY = "team-7Qa1wZ3eR5tY8uI2oP4aS6dF9gH1jK3lM5nB7vC9"
STRONG_CLIENT_KEY = "client-2Ws4xEd6cRf8vTg1bYh3nUj5mIk7oLp9qAz1sXc3"


def test_missing_secret_key_fails():
    with pytest.raises(ImproperlyConfigured):
        validate_production_signing_keys(
            secret_key="",
            client_jwt_signing_key=STRONG_CLIENT_KEY,
        )


def test_repository_development_secret_fails():
    with pytest.raises(ImproperlyConfigured):
        validate_production_signing_keys(
            secret_key="dev-insecure-change-me",
            client_jwt_signing_key=STRONG_CLIENT_KEY,
        )


def test_missing_or_weak_client_key_fails():
    for value in ("", "short", "test-secret-key", "a" * 64):
        with pytest.raises(ImproperlyConfigured):
            validate_production_signing_keys(
                secret_key=STRONG_TEAM_KEY,
                client_jwt_signing_key=value,
            )


def test_client_and_team_keys_must_be_independent():
    with pytest.raises(ImproperlyConfigured):
        validate_production_signing_keys(
            secret_key=STRONG_TEAM_KEY,
            client_jwt_signing_key=STRONG_TEAM_KEY,
        )


def test_strong_independent_values_pass():
    team, client = validate_production_signing_keys(
        secret_key=STRONG_TEAM_KEY,
        client_jwt_signing_key=STRONG_CLIENT_KEY,
    )
    assert team == STRONG_TEAM_KEY
    assert client == STRONG_CLIENT_KEY


def _import_production(extra_env: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SECRET_KEY", None)
    env.pop("CLIENT_JWT_SIGNING_KEY", None)
    env["DATABASE_URL"] = ""
    for key, value in extra_env.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-c", "import itrix.settings.production; print('production-settings-ok')"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_production_import_fails_without_secret_key():
    result = _import_production({"CLIENT_JWT_SIGNING_KEY": STRONG_CLIENT_KEY})
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_import_fails_without_client_key():
    result = _import_production({"SECRET_KEY": STRONG_TEAM_KEY})
    assert result.returncode != 0
    assert "CLIENT_JWT_SIGNING_KEY" in result.stderr


def test_production_import_accepts_strong_independent_keys():
    result = _import_production(
        {
            "SECRET_KEY": STRONG_TEAM_KEY,
            "CLIENT_JWT_SIGNING_KEY": STRONG_CLIENT_KEY,
        }
    )
    assert result.returncode == 0, result.stderr
    assert "production-settings-ok" in result.stdout
