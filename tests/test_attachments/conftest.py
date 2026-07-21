"""Shared attachment fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _blob_root(settings, tmp_path):
    """Point blob storage at a temp dir so tests never touch the real tree."""
    settings.ATTACHMENT_BLOB_ROOT = str(tmp_path / "blobs")
    settings.ENABLE_ATTACHMENTS = True
    return settings.ATTACHMENT_BLOB_ROOT


@pytest.fixture
def thread(db):
    from apps.conversations.services import threads as thread_svc

    return thread_svc.create_thread(visitor_session="sess-attach")
