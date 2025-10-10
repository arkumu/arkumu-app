import csv
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from arkumu.storage.models import S3FileObject, UploadSession


class DummyPaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        bucket = kwargs["Bucket"]
        prefix = kwargs.get("Prefix")
        for page in self.pages.get(bucket, []):
            if prefix:
                filtered = [
                    obj for obj in page.get("Contents", [])
                    if obj.get("Key", "").startswith(prefix)
                ]
                yield {"Contents": filtered}
            else:
                yield page


class DummyS3Client:
    def __init__(self, pages):
        self._pages = pages

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return DummyPaginator(self._pages)


class DummyBaseStorageService:
    def __init__(self, pages):
        self.s3_client = DummyS3Client(pages)


@pytest.mark.django_db
def test_dump_s3_inventory_writes_output_and_reports(monkeypatch, tmp_path):
    pages = {
        "demo": [
            {"Contents": [{"Key": "file-one.txt"}, {"Key": "orphan.txt"}]},
        ]
    }

    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.BaseStorageService",
        lambda: DummyBaseStorageService(pages),
    )
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.ClientError",
        Exception,
    )

    user = get_user_model().objects.create(username="tester")
    session = UploadSession.objects.create(user=user, folder_name="test", s3_bucket="demo")

    S3FileObject.objects.create(
        file_name="file-one.txt",
        s3_key="file-one.txt",
        status="verified",
        organization="demo",
        session=session,
    )
    S3FileObject.objects.create(
        file_name="missing.txt",
        s3_key="missing.txt",
        status="completed",
        organization="demo",
        session=session,
    )

    output = tmp_path / "catalog.json"
    out = io.StringIO()

    call_command(
        "dump_s3_inventory",
        "--bucket",
        "demo",
        "--output",
        str(output),
        "--format",
        "json",
        stdout=out,
    )

    data = json.loads(output.read_text())
    assert len(data["items"]) == 2

    summary = out.getvalue()
    assert "S3FileObject rows examined: 2" in summary
    assert "Marked 1 row(s) as failed" in summary
    assert "S3 objects without DB entries: 1" in summary


@pytest.mark.django_db
def test_dump_s3_inventory_supports_prefix_and_no_compare(monkeypatch, tmp_path):
    pages = {
        "demo": [
            {"Contents": [{"Key": "folder/file-one.txt"}, {"Key": "other/file-two.txt"}]},
        ]
    }
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.BaseStorageService",
        lambda: DummyBaseStorageService(pages),
    )
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.ClientError",
        Exception,
    )

    output = tmp_path / "catalog.csv"
    out = io.StringIO()

    call_command(
        "dump_s3_inventory",
        "--bucket",
        "demo",
        "--prefix",
        "folder/",
        "--output",
        str(output),
        "--format",
        "csv",
        "--dry-run",
        stdout=out,
    )

    rows = list(csv.reader(output.read_text().splitlines()))
    assert rows == [["bucket", "key"], ["demo", "folder/file-one.txt"]]
    assert "Would mark" in out.getvalue()
