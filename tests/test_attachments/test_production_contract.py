from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from itrix.settings.attachment_validation import validate_production_attachments


def _validate(tmp_path, **overrides):
    values = {
        "enabled": True,
        "base_dir": tmp_path / "app",
        "configured_blob_root": str(tmp_path / "durable"),
        "av_command": "scanner --no-summary",
        "process_inline": True,
        "shared_storage_confirmed": False,
    }
    values.update(overrides)
    with patch("itrix.settings.attachment_validation.shutil.which", return_value="/usr/bin/scanner"):
        return validate_production_attachments(**values)


def test_disabled_attachments_need_no_runtime_contract(tmp_path):
    validate_production_attachments(
        enabled=False,
        base_dir=tmp_path,
        configured_blob_root="",
        av_command="",
        process_inline=False,
    )


def test_enabled_attachments_require_explicit_blob_root(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_BLOB_ROOT"):
        _validate(tmp_path, configured_blob_root="")


def test_enabled_attachments_reject_relative_checkout_and_tmp_storage(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="absolute"):
        _validate(tmp_path, configured_blob_root="private_blobs")

    with pytest.raises(ImproperlyConfigured, match="must not use"):
        _validate(tmp_path, configured_blob_root=str(tmp_path / "app" / "private_blobs"))

    with pytest.raises(ImproperlyConfigured, match="must not use"):
        _validate(tmp_path, configured_blob_root="/tmp/attachments")


def test_enabled_attachments_require_external_av(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_AV_COMMAND"):
        _validate(tmp_path, av_command="")


def test_enabled_attachments_require_scanner_executable_in_runtime(tmp_path):
    with patch("itrix.settings.attachment_validation.shutil.which", return_value=None):
        with pytest.raises(ImproperlyConfigured, match="executable is not available"):
            validate_production_attachments(
                enabled=True,
                base_dir=tmp_path / "app",
                configured_blob_root=str(tmp_path / "durable"),
                av_command="missing-scanner --scan",
                process_inline=True,
            )


def test_worker_processing_requires_explicit_shared_storage_confirmation(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_SHARED_STORAGE_CONFIRMED"):
        _validate(tmp_path, process_inline=False, shared_storage_confirmed=False)

    _validate(tmp_path, process_inline=False, shared_storage_confirmed=True)


def test_inline_processing_accepts_explicit_durable_root_and_external_scanner(tmp_path):
    _validate(tmp_path)
