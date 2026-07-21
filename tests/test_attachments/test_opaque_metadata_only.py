"""
An accepted file we cannot read is a SUCCESS, not a failure
(Backend v6.0 §19.7 rule 4, Playbook §13.4).

    NEVER CALL AN ACCEPTED FILE A FAILURE. If a file uploads but cannot be text-extracted,
    that is not an error. Say what happened plainly and carry on. The visitor gave us
    something; we do not tell them it was worthless.
"""

from __future__ import annotations

import pytest

from apps.attachments import policy
from apps.attachments.models import AttachmentStatus
from apps.attachments.services import intake

pytestmark = pytest.mark.django_db


def _process(thread, name, data, mime="application/octet-stream"):
    attachment = intake.stage(thread=thread, filename=name, data=data, declared_mime=mime)
    intake.process(attachment)
    attachment.refresh_from_db()
    return attachment


def test_an_opaque_binary_reaches_READY_not_FAILED(thread):
    attachment = _process(thread, "weights.safetensors", b"\x00\x01\x02\x03opaque-binary")
    assert attachment.status == AttachmentStatus.READY
    assert attachment.status != AttachmentStatus.FAILED


def test_an_opaque_binary_is_marked_metadata_only(thread):
    attachment = _process(thread, "model.bin", b"\x00\x01\x02binary")
    assert attachment.extraction.metadata_only is True


def test_the_visitor_note_is_the_approved_honest_wording(thread):
    attachment = _process(thread, "model.bin", b"\x00\x01\x02binary")
    assert attachment.visitor_note == policy.MSG_NOT_READABLE
    assert "could not read the contents of this format" in attachment.visitor_note
    assert "work from what you tell us about it" in attachment.visitor_note


def test_the_note_never_uses_failure_language(thread):
    attachment = _process(thread, "model.bin", b"\x00\x01\x02binary")
    lowered = attachment.visitor_note.lower()
    for word in ("fail", "error", "invalid", "rejected", "unsupported", "corrupt"):
        assert word not in lowered, f"the note says {word!r} about an accepted file"


def test_metadata_is_still_available_to_the_agent(thread):
    """
    Represented by METADATA ONLY (filename, type, size) — so the model knows the file
    exists rather than assuming nothing was uploaded.
    """
    from apps.attachments.services import excerpts

    attachment = _process(thread, "diagram.bin", b"\x00\x01opaque")
    items = excerpts.for_context(thread, "architecture")
    assert items and items[0]["filename"] == "diagram.bin"
    assert items[0]["metadata_only"] is True


def test_the_fenced_block_explains_it_plainly(thread):
    from apps.attachments.services import excerpts, fencing

    _process(thread, "diagram.bin", b"\x00\x01opaque")
    block = fencing.fence_many(excerpts.for_context(thread, ""))
    assert "could not be read" in block
    assert "Do not describe it as failed" in block


def test_a_readable_file_is_not_marked_metadata_only(thread):
    """The negative tests must not pass because everything is metadata-only."""
    attachment = _process(thread, "notes.txt", b"Our solver is slow.", mime="text/plain")
    assert attachment.extraction.metadata_only is False
    assert attachment.extraction.has_text
