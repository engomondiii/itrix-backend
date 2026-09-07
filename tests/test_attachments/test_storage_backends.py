from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.test import override_settings

from apps.attachments import storage
from apps.attachments.services import intake, retention


S3_SETTINGS = {
    "ATTACHMENT_STORAGE_BACKEND": "s3",
    "ATTACHMENT_S3_BUCKET": "private-attachments",
    "ATTACHMENT_S3_ENDPOINT": "https://storage.example.test",
    "ATTACHMENT_S3_REGION": "auto",
    "ATTACHMENT_S3_ACCESS_KEY_ID": "test-access",
    "ATTACHMENT_S3_SECRET_ACCESS_KEY": "test-secret",
    "ATTACHMENT_S3_PREFIX": "attachments/",
    "ATTACHMENT_S3_ADDRESSING_STYLE": "path",
}


@override_settings(**S3_SETTINGS)
def test_s3_key_is_scoped_and_opaque():
    key = storage.new_blob_key("../../Customer Secret.PDF")
    assert "/" not in key
    assert "Customer" not in key
    assert key.endswith(".pdf")
    assert storage._s3_key(key) == f"attachments/{key}"


@override_settings(**S3_SETTINGS)
def test_s3_client_uses_explicit_endpoint_credentials_region_and_addressing_style():
    with patch("boto3.client") as client:
        storage._s3_client()
    kwargs = client.call_args.kwargs
    assert kwargs["endpoint_url"] == "https://storage.example.test"
    assert kwargs["region_name"] == "auto"
    assert kwargs["aws_access_key_id"] == "test-access"
    assert kwargs["aws_secret_access_key"] == "test-secret"
    assert kwargs["config"].s3["addressing_style"] == "path"


@override_settings(**S3_SETTINGS)
def test_s3_write_read_head_and_delete_use_private_object_operations():
    client = MagicMock()
    client.get_object.return_value = {"Body": io.BytesIO(b"payload")}
    with patch("apps.attachments.storage._s3_client", return_value=client):
        size, digest = storage.write("abc.txt", b"payload")
        assert size == 7
        assert len(digest) == 64
        assert storage.read("abc.txt") == b"payload"
        assert storage.exists("abc.txt") is True
        assert storage.delete("abc.txt") is True

    client.put_object.assert_called_once()
    put = client.put_object.call_args.kwargs
    assert put["Bucket"] == "private-attachments"
    assert put["Key"] == "attachments/abc.txt"
    assert "ACL" not in put
    client.get_object.assert_called_once_with(
        Bucket="private-attachments", Key="attachments/abc.txt"
    )
    client.head_object.assert_called_once_with(
        Bucket="private-attachments", Key="attachments/abc.txt"
    )
    client.delete_object.assert_called_once_with(
        Bucket="private-attachments", Key="attachments/abc.txt"
    )


@override_settings(**S3_SETTINGS)
def test_s3_head_returns_false_only_for_not_found_and_raises_other_provider_errors():
    missing = ClientError(
        {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadObject",
    )
    denied = ClientError(
        {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
        "HeadObject",
    )
    client = MagicMock()
    client.head_object.side_effect = missing
    with patch("apps.attachments.storage._s3_client", return_value=client):
        assert storage.exists("abc.txt") is False
    client.head_object.side_effect = denied
    with patch("apps.attachments.storage._s3_client", return_value=client):
        with pytest.raises(ClientError):
            storage.exists("abc.txt")


@override_settings(ATTACHMENT_STORAGE_BACKEND="filesystem")
def test_secure_materialize_for_scan_is_0600_and_removed_after_context(tmp_path, settings):
    settings.ATTACHMENT_BLOB_ROOT = str(tmp_path / "canonical")
    storage.write("abc.txt", b"sensitive")
    materialized = None
    with storage.materialize("abc.txt") as path:
        materialized = path
        assert path.read_bytes() == b"sensitive"
        assert path.exists()
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600
    assert materialized is not None
    assert not materialized.exists()
    assert storage.read("abc.txt") == b"sensitive"


@pytest.mark.django_db
def test_object_write_is_cleaned_up_when_attachment_db_create_fails():
    with (
        patch("apps.attachments.services.intake.storage.new_blob_key", return_value="orphan.txt"),
        patch(
            "apps.attachments.services.intake.storage.write",
            return_value=(7, "a" * 64),
        ) as write,
        patch("apps.attachments.services.intake.storage.delete", return_value=True) as delete,
        patch("apps.attachments.services.intake.Attachment.objects.create", side_effect=RuntimeError("db down")),
    ):
        with pytest.raises(RuntimeError, match="db down"):
            intake.stage(thread=None, filename="x.txt", data=b"payload")
    write.assert_called_once_with("orphan.txt", b"payload")
    delete.assert_called_once_with("orphan.txt")


@pytest.mark.django_db
def test_purge_refuses_to_record_success_when_durable_blob_delete_fails():
    attachment = MagicMock()
    attachment.blob_key = "confidential.txt"
    with patch("apps.attachments.storage.delete", return_value=False):
        with pytest.raises(RuntimeError, match="blob deletion failed"):
            retention.purge(attachment, reason="visitor_delete")
    attachment.save.assert_not_called()
