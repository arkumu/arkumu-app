import io

import pytest
from django.core.management import call_command

from arkumu.storage.models import S3FileObject


@pytest.mark.django_db
def test_link_s3_files_to_events_only_uses_verified(monkeypatch):
    verified = S3FileObject.objects.create(
        file_name="verified.jpg",
        s3_key="s3://bucket/verified.jpg",
        status="verified",
    )
    skipped = S3FileObject.objects.create(
        file_name="pending.jpg",
        s3_key="s3://bucket/pending.jpg",
        status="pending",
    )

    captured: dict[str, object] = {}

    class DummyMatcher:
        def __init__(self, logger_func, config):
            self.logger_func = logger_func
            self.config = config

        def match_and_link_by_filename_to_resource_value(self, queryset, link_target=None):
            captured["ids"] = list(queryset.values_list("id", flat=True))
            captured["link_target"] = link_target
            return len(captured["ids"]), 0, 0, 0

    monkeypatch.setattr(
        "arkumu.metadata.management.commands.link_s3_files_to_events.FileResourceMatcherService",
        DummyMatcher,
    )

    out = io.StringIO()
    call_command("link_s3_files_to_events", stdout=out)

    assert captured["ids"] == [verified.id]
    assert captured["link_target"] == "event"
    assert skipped.id not in captured["ids"]
    assert "Found 1 unlinked file(s)" in out.getvalue()


@pytest.mark.django_db
def test_link_s3_files_to_digital_objects_only_uses_verified(monkeypatch):
    verified = S3FileObject.objects.create(
        file_name="verified.txt",
        s3_key="s3://bucket/verified.txt",
        status="verified",
    )
    _ignored = S3FileObject.objects.create(
        file_name="failed.txt",
        s3_key="s3://bucket/failed.txt",
        status="failed",
    )

    captured: dict[str, object] = {}

    class DummyMatcher:
        def __init__(self, logger_func, config):
            self.logger_func = logger_func
            self.config = config

        def match_and_link_by_filename_to_resource_value(self, queryset, link_target=None):
            captured["ids"] = list(queryset.values_list("id", flat=True))
            captured["link_target"] = link_target
            return len(captured["ids"]), 0, 0, 0

    monkeypatch.setattr(
        "arkumu.metadata.management.commands.link_s3_files_to_digital_objects.FileResourceMatcherService",
        DummyMatcher,
    )

    out = io.StringIO()
    call_command("link_s3_files_to_digital_objects", stdout=out)

    assert captured["ids"] == [verified.id]
    assert captured["link_target"] == "digital_object"
    assert "Found 1 unlinked file(s)" in out.getvalue()
