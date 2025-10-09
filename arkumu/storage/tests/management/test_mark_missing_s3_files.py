import io

import pytest
from django.core.management import call_command

from arkumu.storage.models import S3FileObject
from arkumu.metadata.models import Resource, ResourceType
from arkumu.users.models import Organization


def _make_resource(org_code: str) -> Resource:
    org, _ = Organization.objects.get_or_create(
        code=org_code,
        defaults={"name": org_code.upper()},
    )
    return Resource.objects.create(
        uri=f"http://arkumu.org/data/{org_code}/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level="restricted",
    )


@pytest.mark.django_db
def test_mark_missing_s3_files_status_filter(monkeypatch):
    def fake_exists(_self):
        return False

    monkeypatch.setattr(S3FileObject, "exists_in_s3", fake_exists)

    resource = _make_resource("rsh")
    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="rsh",
        status="verified",
        related_resource=resource,
    )

    call_command(
        "mark_missing_s3_files",
        "--bucket",
        "rsh",
        "--status",
        "verified",
    )

    obj.refresh_from_db()
    assert obj.status == "failed"


@pytest.mark.django_db
def test_mark_missing_s3_files_dry_run(monkeypatch):
    def fake_exists(_self):
        return False

    monkeypatch.setattr(S3FileObject, "exists_in_s3", fake_exists)

    resource = _make_resource("rsh")
    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="rsh",
        status="verified",
        related_resource=resource,
    )

    out = io.StringIO()
    call_command(
        "mark_missing_s3_files",
        "--bucket",
        "rsh",
        "--status",
        "verified",
        "--dry-run",
        stdout=out,
    )

    obj.refresh_from_db()
    assert obj.status == "verified"
    assert "Missing" in out.getvalue()
