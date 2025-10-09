import pytest
from django.core.management import call_command

from arkumu.storage.models import S3FileObject


@pytest.mark.django_db
def test_set_s3_bucket_org_updates_missing_rows():
    obj_missing = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="",
    )
    obj_existing = S3FileObject.objects.create(
        file_name="keep.txt",
        s3_key="data/keep.txt",
        organization="rsh",
    )

    call_command(
        "set_s3_bucket_org",
        "--organization",
        "det",
        "--prefix",
        "data/",
    )

    obj_missing.refresh_from_db()
    obj_existing.refresh_from_db()
    assert obj_missing.organization == "det"
    assert obj_existing.organization == "rsh"


@pytest.mark.django_db
def test_set_s3_bucket_org_include_existing():
    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="rsh",
    )

    call_command(
        "set_s3_bucket_org",
        "--organization",
        "det",
        "--prefix",
        "data/",
        "--include-existing",
    )

    obj.refresh_from_db()
    assert obj.organization == "det"


@pytest.mark.django_db
def test_set_s3_bucket_org_dry_run():
    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="",
    )

    call_command(
        "set_s3_bucket_org",
        "--organization",
        "det",
        "--prefix",
        "data/",
        "--dry-run",
    )

    obj.refresh_from_db()
    assert obj.organization == ""
