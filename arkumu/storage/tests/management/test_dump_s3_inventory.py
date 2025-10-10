import csv
import json

import pytest
from django.core.management import call_command


class DummyPaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, Bucket):  # noqa: N803
        for page in self.pages.get(Bucket, []):
            yield page


class DummyS3Client:
    def __init__(self, pages):
        self._pages = pages

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return DummyPaginator(self._pages)


class DummyBoto3:
    def __init__(self, pages):
        self._pages = pages

    def client(self, service_name):
        assert service_name == "s3"
        return DummyS3Client(self._pages)


@pytest.mark.django_db
def test_dump_s3_inventory_writes_json(monkeypatch, tmp_path):
    pages = {
        "demo": [
            {"Contents": [{"Key": "file-one.txt"}, {"Key": "folder/file-two.txt"}]},
        ]
    }

    dummy_boto3 = DummyBoto3(pages)
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.boto3",
        dummy_boto3,
    )
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.ClientError",
        Exception,
    )

    output = tmp_path / "catalog.json"

    call_command(
        "dump_s3_inventory",
        "--bucket",
        "demo",
        "--output",
        str(output),
        "--format",
        "json",
    )

    data = json.loads(output.read_text())
    assert len(data["items"]) == 2
    assert data["items"][0] == {"bucket": "demo", "key": "file-one.txt"}


@pytest.mark.django_db
def test_dump_s3_inventory_writes_csv(monkeypatch, tmp_path):
    pages = {
        "demo": [
            {"Contents": [{"Key": "file-one.txt"}]},
        ]
    }
    dummy_boto3 = DummyBoto3(pages)
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.boto3",
        dummy_boto3,
    )
    monkeypatch.setattr(
        "arkumu.storage.management.commands.dump_s3_inventory.ClientError",
        Exception,
    )

    output = tmp_path / "catalog.csv"

    call_command(
        "dump_s3_inventory",
        "--bucket",
        "demo",
        "--output",
        str(output),
        "--format",
        "csv",
    )

    rows = list(csv.reader(output.read_text().splitlines()))
    assert rows == [["bucket", "key"], ["demo", "file-one.txt"]]
