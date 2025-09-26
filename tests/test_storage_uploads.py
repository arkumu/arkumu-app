"""Tests for the storage async upload batch endpoint."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from arkumu.storage.models.upload_tracking import AsyncUploadFile, AsyncUploadSession


@pytest.mark.django_db
def test_batch_presigned_urls_populates_tracking_fields(monkeypatch):
    """Ensure session and file records have required metadata for async uploads."""

    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="uploader",
        email="uploader@example.com",
        password="test-pass"
    )

    client = Client()
    assert client.login(username="uploader", password="test-pass")

    # Mock UploadService to avoid real S3 setup and return deterministic values
    class FakeUploadService:
        def __init__(self):
            self.validate_responses = []

        def validate_upload_request(self, *, file_name, file_size, content_type, user_id):
            return {
                "valid": True,
                "errors": [],
                "warnings": [],
                "normalized_s3_key": f"data/{file_name}",
                "should_use_multipart": False,
            }

        def generate_presigned_upload_url(self, *, file_name, content_type, path_prefix, max_file_size, bucket_name):
            key_prefix = path_prefix or "data"
            return {
                "success": True,
                "url": f"https://example.com/{key_prefix}/{file_name}",
                "fields": {"dummy": "field"},
                "key": f"{key_prefix}/{file_name}",
                "max_file_size": max_file_size,
            }

    monkeypatch.setattr("arkumu.storage.views.upload_views.UploadService", FakeUploadService)

    url = reverse("storage:batch_presigned_urls")
    payload = {
        "files": [
            {
                "name": "file1.txt",
                "size": 128,
                "type": "text/plain",
                "relativePath": "nested/file1.txt",
            },
            {
                "name": "file2.txt",
                "size": 256,
                "type": "text/plain",
            },
        ],
        "folder": "data",
        "organization": "demo-org",
        "total_files": 2,
    }

    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True

    session = AsyncUploadSession.objects.get(id=data["session_id"])
    assert session.base_folder == "data"
    assert session.total_files == 2
    assert session.organization == "demo-org"

    files = list(AsyncUploadFile.objects.filter(session=session).order_by("filename"))
    assert len(files) == 2

    first = files[0]
    assert first.relative_path == "nested/file1.txt"
    assert first.presigned_url.endswith("file1.txt")
    assert first.presigned_fields["dummy"] == "field"

    second = files[1]
    assert second.relative_path == "file2.txt"
    assert second.presigned_url.endswith("file2.txt")
    assert second.presigned_fields["dummy"] == "field"


@pytest.mark.django_db
def test_batch_presigned_urls_supports_chunk_append(monkeypatch):
    """Ensure subsequent chunk requests reuse the same session."""

    user_model = get_user_model()
    user = user_model.objects.create_user(
        username="chunker",
        email="chunker@example.com",
        password="test-pass"
    )

    client = Client()
    assert client.login(username="chunker", password="test-pass")

    class FakeUploadService:
        def validate_upload_request(self, *, file_name, file_size, content_type, user_id):
            return {
                "valid": True,
                "errors": [],
                "warnings": [],
                "normalized_s3_key": f"data/{file_name}",
                "should_use_multipart": False,
            }

        def generate_presigned_upload_url(self, *, file_name, content_type, path_prefix, max_file_size, bucket_name):
            key_prefix = path_prefix or "data"
            return {
                "success": True,
                "url": f"https://example.com/{key_prefix}/{file_name}",
                "fields": {"dummy": "field"},
                "key": f"{key_prefix}/{file_name}",
                "max_file_size": max_file_size,
            }

    monkeypatch.setattr("arkumu.storage.views.upload_views.UploadService", FakeUploadService)

    url = reverse("storage:batch_presigned_urls")

    first_payload = {
        "files": [
            {"name": "part1.txt", "size": 100, "type": "text/plain"},
            {"name": "part2.txt", "size": 100, "type": "text/plain"},
        ],
        "folder": "data",
        "organization": "demo-org",
        "total_files": 4,
    }

    first_response = client.post(url, data=json.dumps(first_payload), content_type="application/json")
    assert first_response.status_code == 200
    first_data = first_response.json()
    assert first_data["success"] is True
    session_id = first_data["session_id"]

    second_payload = {
        "files": [
            {"name": "part3.txt", "size": 100, "type": "text/plain"},
            {"name": "part4.txt", "size": 100, "type": "text/plain"},
        ],
        "folder": "data",
        "organization": "demo-org",
        "total_files": 4,
        "session_id": session_id,
    }

    second_response = client.post(url, data=json.dumps(second_payload), content_type="application/json")
    assert second_response.status_code == 200
    second_data = second_response.json()
    assert second_data["success"] is True
    assert second_data["session_id"] == session_id

    session = AsyncUploadSession.objects.get(id=session_id)
    assert session.total_files == 4
    assert AsyncUploadFile.objects.filter(session=session).count() == 4
