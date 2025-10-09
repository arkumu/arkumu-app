import io
import hashlib

import pytest
from django.core.management import call_command

from arkumu.metadata.models import Resource, ResourceType
from arkumu.storage.models import S3FileObject
from arkumu.users.models import Organization


class DummyS3Client:
    def __init__(self, responses):
        self.responses = responses

    def head_object(self, Bucket, Key):  # noqa: N803
        result = self.responses.get((Bucket, Key))
        if not result or result.get("head") is None:
            raise RuntimeError("Missing")
        return result["head"]

    def get_object(self, Bucket, Key):  # noqa: N803
        result = self.responses.get((Bucket, Key))
        if not result or result.get("body") is None:
            raise RuntimeError("Missing body")
        return {"Body": io.BytesIO(result["body"])}


class DummyBaseStorageService:
    def __init__(self, responses=None):
        self.s3_client = DummyS3Client(responses or {})

    def close(self):
        pass


def _resource(org_code: str = "rsh") -> Resource:
    org, _ = Organization.objects.get_or_create(
        code=org_code,
        defaults={"name": org_code.upper()},
    )
    uri = f"http://arkumu.org/data/{org_code}/entities/projekt/1"
    resource, _ = Resource.objects.get_or_create(
        uri=uri,
        defaults={
            "resource_type": ResourceType.ENTITY,
            "organization": org,
            "public_access_level": "restricted",
        },
    )
    return resource


@pytest.mark.django_db
def test_verify_s3_files_updates_checksum(monkeypatch):
    responses = {
        ("rsh", "data/file.txt"): {"head": {"ETag": '"abc123"'}},
    }

    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_s3_files.BaseStorageService",
        lambda: DummyBaseStorageService(responses),
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="rsh",
        status="verified",
        related_resource=_resource(),
    )

    call_command(
        "verify_s3_files",
        "--bucket",
        "rsh",
    )

    obj.refresh_from_db()
    assert obj.sha256_checksum == "md5:abc123"
    assert obj.status == "verified"
    assert obj.error_message == ""


@pytest.mark.django_db
def test_verify_s3_files_marks_missing(monkeypatch):
    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_s3_files.BaseStorageService",
        lambda: DummyBaseStorageService({}),
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="rsh",
        status="verified",
        related_resource=_resource(),
    )

    call_command(
        "verify_s3_files",
        "--bucket",
        "rsh",
    )

    obj.refresh_from_db()
    assert obj.status == "failed"
    assert obj.error_message == "File missing in S3"


@pytest.mark.django_db
def test_verify_s3_files_streams_multipart(monkeypatch):
    body = b"multipart data for checksum"
    responses = {
        ("rsh", "data/file.bin"): {
            "head": {"ETag": '"abc-2"'},
            "body": body,
        }
    }

    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_s3_files.BaseStorageService",
        lambda: DummyBaseStorageService(responses),
    )

    obj = S3FileObject.objects.create(
        file_name="file.bin",
        s3_key="data/file.bin",
        organization="rsh",
        status="verified",
        related_resource=_resource(),
    )

    call_command(
        "verify_s3_files",
        "--bucket",
        "rsh",
    )

    obj.refresh_from_db()
    expected = hashlib.md5(body).hexdigest()
    assert obj.sha256_checksum == f"md5:{expected}"


@pytest.mark.django_db
def test_verify_s3_files_dry_run(monkeypatch):
    responses = {
        ("rsh", "data/file.txt"): {"head": {"ETag": '"abc123"'}},
    }

    class MixedService(DummyBaseStorageService):
        def __init__(self):
            super().__init__(responses)

        def close(self):
            pass

    monkeypatch.setattr(
        "arkumu.storage.management.commands.verify_s3_files.BaseStorageService",
        MixedService,
    )

    ok = S3FileObject.objects.create(
        file_name="ok.txt",
        s3_key="data/file.txt",
        organization="rsh",
        status="verified",
        related_resource=_resource(),
    )
    missing = S3FileObject.objects.create(
        file_name="missing.txt",
        s3_key="data/missing.txt",
        organization="rsh",
        status="verified",
        related_resource=_resource(),
    )

    out = io.StringIO()
    call_command(
        "verify_s3_files",
        "--bucket",
        "rsh",
        "--dry-run",
        stdout=out,
    )

    ok.refresh_from_db()
    missing.refresh_from_db()
    assert ok.sha256_checksum == ""
    assert missing.status == "verified"
    assert "would update 1 checksum" in out.getvalue().lower()
