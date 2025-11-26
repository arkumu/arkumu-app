from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from arkumu.storage.models import S3FileObject
from arkumu.storage.services.verification_service import (
    annotate_verified_flags,
    verify_single_object,
)


@patch("arkumu.storage.services.verification_service.BaseStorageService")
def test_verify_single_object_creates_entry(mock_storage_service, db):
    mock_client = MagicMock()
    mock_client.head_object.return_value = {
        "ContentLength": 128,
        "ContentType": "text/csv",
        "ETag": '"abc123"',
        "LastModified": datetime.now(tz=timezone.utc),
    }
    mock_storage_service.return_value.s3_client = mock_client

    result = verify_single_object("org", "data/file.csv", "org")

    assert result.success is True
    stored = S3FileObject.objects.get(s3_key="data/file.csv")
    assert stored.status == "verified"
    assert stored.file_size_bytes == 128
    assert stored.etag == '"abc123"'
    assert stored.content_type == "text/csv"


@patch("arkumu.storage.services.verification_service.BaseStorageService")
def test_verify_single_object_missing_updates_status(mock_storage_service, db):
    mock_client = MagicMock()
    mock_client.head_object.side_effect = ClientError({'Error': {'Code': '404'}}, 'HeadObject')
    mock_storage_service.return_value.s3_client = mock_client

    obj = S3FileObject.objects.create(
        s3_key="data/missing.csv",
        file_name="missing.csv",
        organization="org",
        status="completed",
    )

    result = verify_single_object("org", "data/missing.csv", "org", missing_status="failed")
    obj.refresh_from_db()

    assert result.missing is True
    assert obj.status == "failed"
    assert obj.error_message == "File missing in S3"


def test_annotate_verified_flags_marks_items(db):
    S3FileObject.objects.create(
        s3_key="metadata/example.xml",
        file_name="example.xml",
        organization="org",
        status="verified",
    )
    contents = [
        {"type": "folder", "path": "metadata/", "name": "metadata"},
        {"type": "file", "path": "metadata/example.xml", "name": "example.xml"},
    ]

    annotate_verified_flags(contents, "org")

    assert contents[1].get("verified") is True
