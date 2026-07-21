"""
The signed download endpoint (Backend v6.0 §4.4, §19.7 rule 2).

    Blobs are NEVER on a public path. Download is a signed, short-lived,
    AUTHORIZATION-CHECKED endpoint returning Content-Disposition: attachment with a
    restrictive Content-Security-Policy. NO UPLOADED FILE IS EVER EXECUTED, INTERPRETED,
    OR RENDERED INLINE AS HTML OR SVG.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.attachments.services import intake

pytestmark = pytest.mark.django_db


def _client(session="sess-attach"):
    api = APIClient()
    api.cookies["itrix_visitor_session"] = session
    return api


def _ready(thread, name="doc.txt", data=b"hello world", mime="text/plain"):
    attachment = intake.stage(thread=thread, filename=name, data=data, declared_mime=mime)
    intake.process(attachment)
    attachment.refresh_from_db()
    return attachment


def test_the_owner_can_download(thread):
    attachment = _ready(thread)
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response.status_code == 200


def test_another_session_gets_404_not_403(thread):
    """
    404, not 403. A 403 confirms the file exists — the response must not distinguish
    "not yours" from "does not exist".
    """
    attachment = _ready(thread)
    response = _client("sess-attacker").get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response.status_code == 404


def test_content_disposition_forces_a_download(thread):
    attachment = _ready(thread)
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response["Content-Disposition"].startswith("attachment;")


def test_an_html_upload_still_downloads_rather_than_rendering(thread):
    """
    THE ATTACK THIS CLOSES. A stored HTML file served inline is stored XSS on our origin.
    """
    attachment = _ready(thread, name="payload.html",
                        data=b"<script>alert(1)</script>", mime="text/html")
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["Content-Type"] == "application/octet-stream"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response["Content-Security-Policy"]


def test_an_svg_upload_is_not_rendered_inline(thread):
    attachment = _ready(thread, name="logo.svg",
                        data=b"<svg onload=\"alert(1)\"></svg>", mime="image/svg+xml")
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"].startswith("attachment;")


def test_the_filename_header_cannot_be_injected(thread):
    """
    A filename is attacker-controlled; header injection must be impossible.

    The sanitizer is an ALLOW-LIST rather than a strip-list, so the residue of an
    injection attempt does not survive inside the header value either.
    """
    attachment = _ready(thread, name='evil".txt\r\nX-Injected: yes')
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    disposition = response["Content-Disposition"]

    assert "\r" not in disposition and "\n" not in disposition
    assert '"' not in disposition.split("filename=")[1][1:-1]
    assert ":" not in disposition.split("filename=")[1]
    # No header was actually created.
    assert not response.has_header("X-Injected")


def test_a_traversal_filename_is_reduced_to_a_basename(thread):
    """'../../etc/passwd' is a filename. It must not survive as a path."""
    attachment = _ready(thread, name="../../etc/passwd")
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert "/" not in response["Content-Disposition"]
    assert ".." not in response["Content-Disposition"]


def test_an_ordinary_filename_survives_intact(thread):
    """The sanitizer must not mangle normal names."""
    attachment = _ready(thread, name="Q3 architecture review (final).txt")
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert "Q3 architecture review (final).txt" in response["Content-Disposition"]


def test_a_quarantined_file_cannot_be_downloaded(thread):
    """Release requires a deliberate, logged team action."""
    import io, zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("big.txt", b"0" * 20_000_000)
    attachment = _ready(thread, name="bomb.zip", data=buffer.getvalue(),
                        mime="application/zip")
    assert attachment.status == "quarantined"
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert response.status_code == 404


def test_a_download_is_audited(thread):
    attachment = _ready(thread)
    _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert attachment.audit_entries.filter(action="download").exists()


def test_the_response_is_not_cacheable(thread):
    attachment = _ready(thread)
    response = _client().get(f"/api/v1/attachments/{attachment.id}/download/")
    assert "no-store" in response["Cache-Control"]
