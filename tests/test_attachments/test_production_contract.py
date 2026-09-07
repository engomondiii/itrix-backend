from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from itrix.settings.attachment_validation import validate_production_attachments


# pytest's tmp_path normally lives under /tmp on Linux, while the production contract
# intentionally rejects /tmp as canonical storage. Positive filesystem tests therefore
# use a synthetic durable absolute path; the structural validator does not touch it.
DURABLE_ROOT = "/var/lib/itrix-test-attachments"


def _values(tmp_path, **overrides):
    values = {
        "enabled": True,
        "base_dir": tmp_path / "app",
        "storage_backend": "filesystem",
        "configured_blob_root": DURABLE_ROOT,
        "s3_bucket": "",
        "s3_endpoint": "",
        "s3_region": "",
        "s3_access_key_id": "",
        "s3_secret_access_key": "",
        "s3_prefix": "",
        "s3_addressing_style": "",
        "av_command": "scanner --no-summary",
        "process_inline": True,
        "shared_storage_confirmed": False,
    }
    values.update(overrides)
    return values


def _validate(tmp_path, **overrides):
    with patch(
        "itrix.settings.attachment_validation._executable_available", return_value=True
    ):
        return validate_production_attachments(**_values(tmp_path, **overrides))


def _validate_s3(tmp_path, **overrides):
    values = {
        "storage_backend": "s3",
        "configured_blob_root": "",
        "s3_bucket": "attachments-test",
        "s3_endpoint": "https://storage.example.test",
        "s3_region": "auto",
        "s3_access_key_id": "test-access-key",
        "s3_secret_access_key": "test-secret-key",
        "s3_prefix": "attachments/",
        "s3_addressing_style": "path",
    }
    values.update(overrides)
    return _validate(tmp_path, **values)


def test_disabled_attachments_need_no_runtime_contract(tmp_path):
    values = _values(
        tmp_path,
        enabled=False,
        storage_backend="",
        configured_blob_root="",
        av_command="",
    )
    validate_production_attachments(**values)


def test_enabled_attachments_require_supported_storage_backend(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_STORAGE_BACKEND"):
        _validate(tmp_path, storage_backend="")
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_STORAGE_BACKEND"):
        _validate(tmp_path, storage_backend="public-http")


def test_filesystem_requires_explicit_durable_absolute_root(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_BLOB_ROOT"):
        _validate(tmp_path, configured_blob_root="")
    with pytest.raises(ImproperlyConfigured, match="absolute"):
        _validate(tmp_path, configured_blob_root="private_blobs")


def test_filesystem_rejects_checkout_local_and_tmp_storage(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="must not use"):
        _validate(tmp_path, configured_blob_root=str(tmp_path / "app" / "private_blobs"))
    with pytest.raises(ImproperlyConfigured, match="must not use"):
        _validate(tmp_path, configured_blob_root="/tmp/attachments")


def test_filesystem_inline_processing_accepts_durable_root_and_scanner(tmp_path):
    _validate(tmp_path)


def test_filesystem_worker_requires_shared_storage_confirmation(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_SHARED_STORAGE_CONFIRMED"):
        _validate(tmp_path, process_inline=False, shared_storage_confirmed=False)
    _validate(tmp_path, process_inline=False, shared_storage_confirmed=True)


def test_s3_mode_accepts_without_blob_root_and_without_network(tmp_path):
    with patch("boto3.client") as boto_client:
        _validate_s3(tmp_path, configured_blob_root="")
    boto_client.assert_not_called()


@pytest.mark.parametrize(
    ("field", "setting"),
    [
        ("s3_bucket", "ATTACHMENT_S3_BUCKET"),
        ("s3_endpoint", "ATTACHMENT_S3_ENDPOINT"),
        ("s3_region", "ATTACHMENT_S3_REGION"),
        ("s3_access_key_id", "ATTACHMENT_S3_ACCESS_KEY_ID"),
        ("s3_secret_access_key", "ATTACHMENT_S3_SECRET_ACCESS_KEY"),
        ("s3_prefix", "ATTACHMENT_S3_PREFIX"),
    ],
)
def test_s3_mode_requires_complete_nonblank_configuration(tmp_path, field, setting):
    with pytest.raises(ImproperlyConfigured, match=setting):
        _validate_s3(tmp_path, **{field: ""})


def test_s3_endpoint_must_be_http_or_https(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_S3_ENDPOINT"):
        _validate_s3(tmp_path, s3_endpoint="storage.example.test")


def test_s3_bucket_must_not_be_a_path(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_S3_BUCKET"):
        _validate_s3(tmp_path, s3_bucket="folder/bucket")


@pytest.mark.parametrize("prefix", ["/attachments/", "../attachments/", "attachments\\private/"])
def test_s3_prefix_must_be_structurally_safe(tmp_path, prefix):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_S3_PREFIX"):
        _validate_s3(tmp_path, s3_prefix=prefix)


def test_s3_prefix_must_end_in_separator(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_S3_PREFIX"):
        _validate_s3(tmp_path, s3_prefix="attachments")


@pytest.mark.parametrize("style", ["auto", "virtual", "path"])
def test_s3_addressing_style_accepts_supported_values(tmp_path, style):
    _validate_s3(tmp_path, s3_addressing_style=style)


@pytest.mark.parametrize("style", ["", "dns", "bucket"])
def test_s3_addressing_style_rejects_unsupported_or_blank_values(tmp_path, style):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_S3_ADDRESSING_STYLE"):
        _validate_s3(tmp_path, s3_addressing_style=style)


def test_external_av_command_is_required_in_both_modes(tmp_path):
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_AV_COMMAND"):
        _validate(tmp_path, av_command="")
    with pytest.raises(ImproperlyConfigured, match="ATTACHMENT_AV_COMMAND"):
        _validate_s3(tmp_path, av_command="")


def test_missing_av_executable_is_rejected_at_actual_validation_seam(tmp_path):
    with patch(
        "itrix.settings.attachment_validation._executable_available", return_value=False
    ):
        with pytest.raises(ImproperlyConfigured, match="executable is not available"):
            validate_production_attachments(
                **_values(tmp_path, av_command="missing-scanner --scan")
            )


def test_s3_non_inline_does_not_need_filesystem_shared_mount_assertion(tmp_path):
    _validate_s3(tmp_path, process_inline=False, shared_storage_confirmed=False)
