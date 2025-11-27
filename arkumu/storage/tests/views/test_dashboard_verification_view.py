from unittest.mock import MagicMock, patch

from arkumu.storage.models import S3FileObject
from arkumu.storage.views.dashboard_views import verify_file, verify_prefix


@patch("arkumu.storage.views.dashboard_views.BucketService")
@patch("arkumu.storage.views.dashboard_views.verify_single_object")
def test_verify_file_view_returns_updated_row(mock_verify, mock_bucket_service, prepared_request, db):
    mock_bucket = mock_bucket_service.return_value
    mock_bucket.get_organization_bucket.return_value = "org"
    mock_bucket.list_bucket_contents.return_value = [
        {"type": "file", "path": "data/file.csv", "name": "file.csv", "size": 100},
    ]
    mock_verify.return_value = MagicMock(success=True, missing=False, error=None)

    S3FileObject.objects.create(
        s3_key="data/file.csv",
        file_name="file.csv",
        organization="org",
        status="verified",
    )

    request = prepared_request(
        "/storage/dashboard/verify-file/",
        data={"organization": "org", "path": "data/file.csv", "prefix": ""},
    )
    assert request.POST.get("organization") == "org"
    assert request.POST.get("path") == "data/file.csv"

    response = verify_file(request)

    assert response.status_code == 200
    content = response.content.decode()
    assert "badge-success" in content
    assert "storage-dashboard-alerts" in content
    mock_verify.assert_called_once()


@patch("arkumu.storage.views.dashboard_views.verify_s3_prefix")
@patch("arkumu.storage.views.dashboard_views.BucketService")
def test_verify_prefix_schedules_task(mock_bucket_service, mock_task, prepared_request):
    mock_bucket = mock_bucket_service.return_value
    mock_bucket.get_organization_bucket.return_value = "org"

    request = prepared_request(
        "/storage/dashboard/verify-prefix/",
        data={"organization": "org", "prefix": "data/"},
    )
    assert request.POST.get("organization") == "org"
    assert request.POST.get("prefix") == "data/"

    response = verify_prefix(request)

    assert response.status_code == 200
    mock_task.schedule.assert_called_once()
    scheduled_args = mock_task.schedule.call_args.kwargs.get("args")
    assert scheduled_args == ("org", "data/", "org")
    assert "storage-dashboard-alerts" in response.content.decode()
