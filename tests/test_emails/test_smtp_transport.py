"""
THE CUSTOM-DOMAIN MAIL TRANSPORT (2026-08-13).

Outbound mail moved off the Gmail app password and onto the gpslab.org mail server:
mail.gpslab.org, port 465, implicit SSL, authenticating as itrix@gpslab.org.

── WHY THE TRANSPORT IS DERIVED FROM THE PORT ───────────────────────────────
465 is implicit SSL; 587 is STARTTLS. Django raises ImproperlyConfigured when
EMAIL_USE_TLS and EMAIL_USE_SSL are both true, and Railway carries an explicit value for
neither — so reading them as two independent booleans is how a port change silently
produces the wrong handshake. 465 with STARTTLS does not error: it hangs until
EMAIL_TIMEOUT and is recorded as a send failure, which reads as a bad password.

These tests pin the derivation and the conflict guard, because both failures are silent.
"""

from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, **environ):
    """Re-import the settings module under a given environment and hand it back."""
    for key in (
        "EMAIL_HOST", "EMAIL_PORT", "EMAIL_USE_SSL", "EMAIL_USE_TLS",
        "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "EMAIL_FROM", "EMAIL_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)

    import itrix.settings.base as base

    return importlib.reload(base)


def test_the_defaults_are_the_gpslab_mailbox(monkeypatch):
    base = _reload_settings(monkeypatch)

    assert base.EMAIL_HOST == "mail.gpslab.org"
    assert base.EMAIL_PORT == 465
    assert base.EMAIL_HOST_USER == "itrix@gpslab.org"


def test_port_465_derives_implicit_ssl(monkeypatch):
    base = _reload_settings(monkeypatch)

    assert base.EMAIL_USE_SSL is True
    assert base.EMAIL_USE_TLS is False


def test_port_587_derives_starttls(monkeypatch):
    """The derivation is by PORT, so moving back to 587 needs no second variable."""
    base = _reload_settings(monkeypatch, EMAIL_PORT="587")

    assert base.EMAIL_USE_TLS is True
    assert base.EMAIL_USE_SSL is False


def test_both_transports_set_is_resolved_rather_than_left_to_crash(monkeypatch):
    """Django rejects the combination. Resolving it at boot beats failing at send."""
    base = _reload_settings(monkeypatch, EMAIL_USE_SSL="True", EMAIL_USE_TLS="True")

    assert not (base.EMAIL_USE_SSL and base.EMAIL_USE_TLS)
    assert base.EMAIL_USE_SSL is True
    assert base.EMAIL_TRANSPORT_CONFLICT is True


def test_no_conflict_flag_when_the_configuration_is_coherent(monkeypatch):
    assert _reload_settings(monkeypatch).EMAIL_TRANSPORT_CONFLICT is False


def test_an_explicit_transport_still_wins(monkeypatch):
    """A host on 465 that genuinely wants STARTTLS can say so."""
    base = _reload_settings(monkeypatch, EMAIL_USE_SSL="False", EMAIL_USE_TLS="True")

    assert base.EMAIL_USE_TLS is True
    assert base.EMAIL_USE_SSL is False


def test_the_sender_becomes_the_authenticated_mailbox(monkeypatch):
    """
    A mail server refuses a From it does not own (553), at send time, in a background
    task — after the visitor has been told to check their inbox. So the authenticated
    mailbox wins and the discrepancy is reported.
    """
    base = _reload_settings(
        monkeypatch, EMAIL_HOST_PASSWORD="mailbox-secret", EMAIL_FROM="gpslab@iwl.kr"
    )

    assert base.EMAIL_PROVIDER == "smtp"
    assert base.EMAIL_FROM == "itrix@gpslab.org"
    assert base.EMAIL_FROM_IGNORED == "gpslab@iwl.kr"
    assert base.DEFAULT_FROM_EMAIL == "iTrix Assessment Team <itrix@gpslab.org>"


def test_a_matching_email_from_is_not_reported_as_ignored(monkeypatch):
    base = _reload_settings(
        monkeypatch, EMAIL_HOST_PASSWORD="mailbox-secret", EMAIL_FROM="itrix@gpslab.org"
    )

    assert base.EMAIL_FROM_IGNORED == ""


def test_a_pasted_password_keeps_no_whitespace(monkeypatch):
    """A trailing newline from a copy-paste fails SMTP AUTH like a wrong password does."""
    base = _reload_settings(monkeypatch, EMAIL_HOST_PASSWORD="  abcd efgh\nijkl  ")

    assert base.EMAIL_HOST_PASSWORD == "abcdefghijkl"


def test_no_credential_has_a_default(monkeypatch):
    """A password with a source-control fallback is a password in every clone and CI log."""
    base = _reload_settings(monkeypatch)

    assert base.EMAIL_HOST_PASSWORD == ""
    assert base.EMAIL_PROVIDER == "none"
