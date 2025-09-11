import csv
import io
import pytest

from django.contrib.auth import get_user_model

from arkumu.storage.models import UploadSession, S3FileObject
from arkumu.storage.services.bucket_service import BucketService


class _HeadClientStub:
    def __init__(self, mapping):
        self.mapping = mapping

    def head_object(self, Bucket, Key):
        return self.mapping.get(Key, {})


@pytest.mark.django_db
def test_export_successful_imports_csv_basic(user, monkeypatch):
    """Exports only completed/verified files for the org and includes checksums when available."""
    org = "fuk"

    # Create upload session associated with the organization
    session = UploadSession.objects.create(
        user=user,
        folder_name="data",
        status="in_progress",
        total_files=2,
        total_size_bytes=123,
        institution=org,
        s3_bucket=org,
    )

    # Successful files
    f1 = S3FileObject.objects.create(
        session=session,
        file_name="a_file.pdf",
        s3_key=f"{org}/data/a_file.pdf",
        file_size_bytes=100,
        status="completed",
    )
    f2 = S3FileObject.objects.create(
        session=session,
        file_name="b_file.pdf",
        s3_key=f"{org}/metadata/b_file.pdf",
        file_size_bytes=200,
        status="verified",
    )

    # Failed file should not be exported
    S3FileObject.objects.create(
        session=session,
        file_name="c_file.pdf",
        s3_key=f"{org}/data/c_file.pdf",
        file_size_bytes=300,
        status="failed",
    )

    service = BucketService()

    # Avoid real S3 calls for bucket existence
    monkeypatch.setattr(
        service,
        "ensure_organization_bucket_exists",
        lambda organization_id, check_only=True, auto_create=True: {
            "success": True,
            "bucket_name": organization_id,
            "status": "exists",
        },
    )

    # Stub head_object to return checksums
    head_map = {
        f1.s3_key: {"ChecksumSHA256": "sha256_from_header_1"},
        f2.s3_key: {"Metadata": {"sha256": "sha256_from_metadata_2"}},
    }
    service.base_s3_service.s3_client = _HeadClientStub(head_map)

    result = service.export_successful_imports_csv(org)
    assert result["success"] is True
    content = result["content"]
    assert isinstance(content, (bytes, bytearray))

    # Parse CSV
    rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))
    assert rows[0] == [
        "file_name",
        "folder_name",
        "file_size_bytes",
        "file_size_human",
        "s3_key",
        "checksum_sha256",
    ]

    # Expect 2 data rows
    assert len(rows) == 3

    # Make a dict by s3_key for easier assertions
    data = {r[4]: r for r in rows[1:]}
    assert data[f1.s3_key][0] == "a_file.pdf"
    assert data[f1.s3_key][5] == "sha256_from_header_1"

    assert data[f2.s3_key][0] == "b_file.pdf"
    assert data[f2.s3_key][5] == "sha256_from_metadata_2"

