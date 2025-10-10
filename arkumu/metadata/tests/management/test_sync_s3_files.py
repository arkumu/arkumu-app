import io

import pytest
from django.core.management import call_command, CommandError

from arkumu.storage.models import S3FileObject


class DummyService:
    def __init__(self, logger_func, config):
        self.logger_func = logger_func
        self.calls = []

    def discover_and_sync_s3_files(self, bucket_name: str, prefix: str):
        self.calls.append((bucket_name, prefix))
        self.logger_func("discover called")
        return 0, 0, 0, 0


@pytest.mark.django_db
def test_sync_s3_files_updates_status(monkeypatch):
    monkeypatch.setattr(
        "arkumu.metadata.management.commands.sync_s3_files.FileResourceMatcherService",
        DummyService,
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="det",
        status="pending",
    )

    call_command(
        "sync_s3_files",
        "--bucket",
        "det",
        "--prefix",
        "data/",
        "--set-status",
        "completed",
        "--from-status",
        "pending",
    )

    obj.refresh_from_db()
    assert obj.status == "completed"


@pytest.mark.django_db
def test_sync_s3_files_validates_status(monkeypatch):
    monkeypatch.setattr(
        "arkumu.metadata.management.commands.sync_s3_files.FileResourceMatcherService",
        DummyService,
    )

    with pytest.raises(CommandError):
        call_command(
            "sync_s3_files",
            "--bucket",
            "det",
            "--set-status",
            "unknown",
        )


@pytest.mark.django_db
def test_sync_s3_files_reports_dry_run(monkeypatch):
    monkeypatch.setattr(
        "arkumu.metadata.management.commands.sync_s3_files.FileResourceMatcherService",
        DummyService,
    )

    obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/file.txt",
        organization="det",
        status="pending",
    )

    out = io.StringIO()
    call_command(
        "sync_s3_files",
        "--bucket",
        "det",
        "--set-status",
        "verified",
        "--from-status",
        "pending",
        "--dry-run",
        stdout=out,
    )

    obj.refresh_from_db()
    assert obj.status == "pending"
    assert "would update 1" in out.getvalue()
