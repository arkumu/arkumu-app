import io
from typing import Tuple

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.core.management import call_command

from arkumu.storage.models import S3FileObject, UploadSession


HEAD_CALLS: list[Tuple[str, str]] = []


class DummyS3Client:
    def __init__(self, responses):
        self._responses = responses

    def head_object(self, Bucket, Key):  # noqa: N803
        HEAD_CALLS.append((Bucket, Key))
        result = self._responses.get((Bucket, Key))
        if result is None:
            raise ClientError(
                {
                    "Error": {
                        "Code": "404",
                        "Message": "Not Found",
                        "BucketName": Bucket,
                        "Key": Key,
                    }
                },
                "HeadObject",
            )
        return result


class DummyBaseStorageService:
    def __init__(self, responses=None):
        self.s3_client = DummyS3Client(responses or {})

    def close(self):
        pass


@pytest.mark.django_db
def test_verify_full_s3_keys_updates_fields(monkeypatch):
    HEAD_CALLS.clear()
    responses = {
        ("arkumu-bucket", "folder/file.txt"): {"ETag": '"abc123"'},
    }
    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_full_s3_keys.BaseStorageService",
        lambda: DummyBaseStorageService(responses),
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="s3://arkumu-bucket/folder/file.txt",
        status="pending",
        organization="",
    )

    out = io.StringIO()
    call_command("verify_full_s3_keys", stdout=out)

    obj.refresh_from_db()
    assert obj.status == "verified"
    assert obj.etag == '"abc123"'
    assert obj.organization == "arkumu-bucket"
    assert "Newly verified 1" in out.getvalue()
    assert "Newly missing 0" in out.getvalue()


@pytest.mark.django_db
def test_verify_full_s3_keys_dry_run(monkeypatch):
    HEAD_CALLS.clear()
    responses = {
        ("arkumu-bucket", "folder/file.txt"): {"ETag": '"abc123"'},
    }
    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_full_s3_keys.BaseStorageService",
        lambda: DummyBaseStorageService(responses),
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="s3://arkumu-bucket/folder/file.txt",
        status="pending",
        organization="",
    )

    out = io.StringIO()
    call_command("verify_full_s3_keys", "--dry-run", stdout=out)

    obj.refresh_from_db()
    assert obj.status == "pending"
    assert obj.etag == ""
    assert obj.organization == ""
    assert "Would verify 1 object" in out.getvalue()
    assert "Would newly verify 1" in out.getvalue()
    assert "Would mark as missing 0" in out.getvalue()


@pytest.mark.django_db
def test_verify_full_s3_keys_uses_fallback_bucket(monkeypatch):
    HEAD_CALLS.clear()
    responses = {
        ("fuk", "data/sample.txt"): {"ETag": '"etag-1"'},
    }
    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_full_s3_keys.BaseStorageService",
        lambda: DummyBaseStorageService(responses),
    )

    user = get_user_model().objects.create(username="tester")
    session = UploadSession.objects.create(user=user, folder_name="test", s3_bucket="fuk")

    obj = S3FileObject.objects.create(
        file_name="sample.txt",
        s3_key="data/sample.txt",
        status="completed",
        session=session,
        organization="",
    )

    call_command("verify_full_s3_keys")

    obj.refresh_from_db()
    assert HEAD_CALLS == [("fuk", "data/sample.txt")]
    assert obj.status == "verified"
    assert obj.etag == '"etag-1"'
    assert obj.organization == "fuk"


@pytest.mark.django_db
def test_verify_full_s3_keys_handles_missing(monkeypatch):
    HEAD_CALLS.clear()
    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_full_s3_keys.BaseStorageService",
        lambda: DummyBaseStorageService({}),
    )

    obj = S3FileObject.objects.create(
        file_name="missing.txt",
        s3_key="s3://arkumu-bucket/folder/missing.txt",
        status="pending",
        organization="",
    )

    call_command("verify_full_s3_keys")

    obj.refresh_from_db()
    assert obj.status == "missing"
    assert obj.etag == ""
    assert obj.organization == ""
    assert obj.error_message.startswith("File missing in S3")
