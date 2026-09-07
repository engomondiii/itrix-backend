from __future__ import annotations

import hashlib
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.attachments.models import AttachmentScan
from apps.attachments.runtime_validation import (
    AttachmentRuntimeValidationError,
    validate_attachment_runtime,
)


@override_settings(ENABLE_ATTACHMENTS=False)
def test_runtime_validator_skips_all_probes_when_disabled():
    with patch("apps.attachments.runtime_validation.storage.write") as write:
        report = validate_attachment_runtime()
    assert report == {"enabled": False, "validated": True}
    write.assert_not_called()


@override_settings(ENABLE_ATTACHMENTS=True, ATTACHMENT_AV_COMMAND="clamscan --no-summary")
def test_runtime_validator_proves_write_read_scan_and_durable_delete_without_customer_data():
    captured = {}

    def write(_key, payload):
        captured["payload"] = payload
        return len(payload), hashlib.sha256(payload).hexdigest()

    with (
        patch("apps.attachments.runtime_validation.storage.new_blob_key", return_value="probe.txt"),
        patch("apps.attachments.runtime_validation.storage.write", side_effect=write) as write_mock,
        patch("apps.attachments.runtime_validation.storage.read", side_effect=lambda _key: captured["payload"]),
        patch("apps.attachments.runtime_validation.storage.exists", side_effect=[True, False]) as exists,
        patch("apps.attachments.runtime_validation.storage.delete", return_value=True) as delete,
        patch("apps.attachments.runtime_validation.storage.materialize", return_value=nullcontext(Path("/secure/probe.scan"))),
        patch("apps.attachments.runtime_validation.storage.backend_name", return_value="s3"),
        patch(
            "apps.attachments.runtime_validation.scanner._external_av",
            return_value=(AttachmentScan.Verdict.CLEAN, "clean"),
        ) as av,
    ):
        report = validate_attachment_runtime()

    assert report["validated"] is True
    assert report["storage_backend"] == "s3"
    assert report["probe_deleted"] is True
    assert captured["payload"].startswith(b"itriX attachment runtime validation probe\n")
    write_mock.assert_called_once()
    av.assert_called_once_with("/secure/probe.scan")
    delete.assert_called_once_with("probe.txt")
    assert exists.call_count == 2


@override_settings(ENABLE_ATTACHMENTS=True, ATTACHMENT_AV_COMMAND="clamscan --no-summary")
def test_runtime_validator_cleans_up_probe_when_integrity_check_fails():
    with (
        patch("apps.attachments.runtime_validation.storage.new_blob_key", return_value="probe.txt"),
        patch(
            "apps.attachments.runtime_validation.storage.write",
            side_effect=lambda _key, payload: (len(payload), hashlib.sha256(payload).hexdigest()),
        ),
        patch("apps.attachments.runtime_validation.storage.exists", side_effect=[True, False]),
        patch("apps.attachments.runtime_validation.storage.read", return_value=b"wrong bytes"),
        patch("apps.attachments.runtime_validation.storage.delete", return_value=True) as delete,
    ):
        with pytest.raises(AttachmentRuntimeValidationError, match="read integrity"):
            validate_attachment_runtime()
    delete.assert_called_once_with("probe.txt")


@override_settings(ENABLE_ATTACHMENTS=True, ATTACHMENT_AV_COMMAND="clamscan --no-summary")
def test_runtime_validator_fails_if_probe_cannot_be_durably_deleted():
    with (
        patch("apps.attachments.runtime_validation.storage.new_blob_key", return_value="probe.txt"),
        patch(
            "apps.attachments.runtime_validation.storage.write",
            side_effect=lambda _key, payload: (len(payload), hashlib.sha256(payload).hexdigest()),
        ),
        patch("apps.attachments.runtime_validation.storage.exists", return_value=True),
        patch("apps.attachments.runtime_validation.storage.read", side_effect=lambda _key: Mock()),
        patch("apps.attachments.runtime_validation.storage.delete", return_value=False),
    ):
        with pytest.raises(AttachmentRuntimeValidationError, match="durably deleted"):
            validate_attachment_runtime()


def test_management_command_reports_disabled_runtime_without_secrets(capsys):
    with patch(
        "apps.attachments.management.commands.validate_attachment_runtime.validate_attachment_runtime",
        return_value={"enabled": False, "validated": True},
    ):
        call_command("validate_attachment_runtime")
    assert "runtime probe skipped" in capsys.readouterr().out
