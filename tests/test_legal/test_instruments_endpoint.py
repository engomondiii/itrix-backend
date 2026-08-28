"""
``GET legal/instruments/`` and ``POST portal/legal/assent/`` (Backend v7.1 §15.1).

── WHAT THE PUBLIC ENDPOINT MUST NOT BE ────────────────────────────────────
An oracle. It serves versions and dates and nothing about anyone — it describes the platform,
not its users. Every other unauthenticated endpoint on this backend is careful about that, and
a legal-metadata route is an easy place to forget.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_the_public_endpoint_serves_versions_and_names_nobody():
    body = APIClient().get("/api/v1/legal/instruments/").json()

    slugs = [i["slug"] for i in body["instruments"]]
    assert slugs == ["terms", "privacy", "security", "disclosure-policy"]
    for instrument in body["instruments"]:
        assert instrument["version"], "an instrument with no version cannot be assented to"
        assert instrument["title"]

    # It describes the platform, not its users.
    raw = str(body)
    for forbidden in ("@", "client", "lead", "email"):
        assert forbidden not in raw.lower().replace("disclosure-policy", "")


def test_the_endpoint_names_which_instruments_assent_binds():
    """
    So a client cannot decide for itself which instruments a checkbox should cover. The two
    lists drifting would make the record claim more than the visitor was shown.
    """
    body = APIClient().get("/api/v1/legal/instruments/").json()
    assert body["assentRequired"] == ["terms", "privacy"]


def test_it_serves_the_instruments_even_when_unpublished(settings):
    """
    A visitor must ALWAYS be able to read what governs their use. What ``published: false``
    changes is the presentation — itrix-web renders a draft banner and a noindex — not the
    availability. An unreviewed Terms presented as authoritative is worse than a delayed one;
    an unavailable Terms is worse than both.
    """
    settings.LEGAL_PUBLISHED = False
    body = APIClient().get("/api/v1/legal/instruments/").json()
    assert body["published"] is False
    assert len(body["instruments"]) == 4


def test_it_needs_no_authentication():
    response = APIClient().get("/api/v1/legal/instruments/")
    assert response.status_code == 200


def test_the_assent_endpoint_refuses_without_a_client_session():
    """
    It records assent FOR A CLIENT. Without one there is no subject, and a record naming nobody
    attests to nothing.
    """
    response = APIClient().post("/api/v1/portal/legal/assent/", {}, format="json")
    assert response.status_code in (401, 403)


def test_a_version_mismatch_is_logged_loudly_but_the_server_versions_are_stored(settings):
    """
    ── THE CLIENT'S VERSIONS ARE ACCEPTED AND THEN IGNORED ─────────────────
    The frontend sends what it RENDERED, which is the honest thing for it to send. The record
    stores the SERVER's versions, because the client is untrusted and a request could claim any
    version at all.

    What the client's copy is FOR is this check: if it disagrees, the visitor read something
    other than what binds them, and that deserves a loud log rather than a silent write.
    """
    from django.db import transaction
    from unittest.mock import patch

    from apps.legal.services import assent as assent_svc
    from apps.legal.views import PortalAssentView

    settings.LEGAL_PUBLISHED = True
    settings.LEGAL_TERMS_VERSION = "1.1"
    # ``itrix`` deliberately owns its console handler with ``propagate=False``.  Patch
    # the logger method directly so this test verifies the actual contract (an ERROR is
    # emitted) without depending on pytest's root-log capture implementation.
    with patch("apps.legal.views.logger.error") as logged:
        PortalAssentView._warn_on_version_mismatch([{"slug": "terms", "version": "0.9"}])
    logged.assert_called_once()
    assert "legal.version_mismatch" in logged.call_args.args[0]

    # And the write still stores the server's version.
    with transaction.atomic():
        record = assent_svc.record_in_transaction(email="v@example.com", path="reprompt")
    assert record.version_of("terms") == "1.1"


def test_a_matching_version_logs_nothing(settings):
    from unittest.mock import patch

    from apps.legal.views import PortalAssentView

    settings.LEGAL_PUBLISHED = True
    settings.LEGAL_TERMS_VERSION = "1.1"
    with patch("apps.legal.views.logger.error") as logged:
        PortalAssentView._warn_on_version_mismatch([{"slug": "terms", "version": "1.1"}])
    logged.assert_not_called()


def test_the_admin_cannot_edit_an_assent_record():
    """
    An assent record is evidence. If an admin could edit one, every record in the table would be
    worth nothing — the value of the evidence is that nobody can change it after the fact,
    including us.
    """
    from apps.legal.admin import AssentRecordAdmin
    from apps.legal.models import AssentRecord

    admin = AssentRecordAdmin(AssentRecord, None)
    assert admin.has_add_permission(None) is False
    assert admin.has_change_permission(None) is False
    assert admin.has_delete_permission(None) is False
