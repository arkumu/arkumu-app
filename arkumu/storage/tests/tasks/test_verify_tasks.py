from unittest.mock import MagicMock, patch

from arkumu.storage import tasks


@patch("arkumu.storage.services.verification_service.verify_single_object")
def test_verify_s3_file_task_invokes_helper(mock_verify):
    mock_verify.return_value = MagicMock(success=True, missing=False, error=None)

    tasks.verify_s3_file("bucket", "key", "org")

    mock_verify.assert_called_once_with("bucket", "key", "org")


@patch("arkumu.storage.services.verification_service.verify_single_object")
@patch("arkumu.storage.services.verification_service.iter_objects_under_prefix")
def test_verify_s3_prefix_task_iterates_keys(mock_iter, mock_verify):
    mock_iter.return_value = ["data/a.csv", "data/b.csv"]
    mock_verify.side_effect = [
        MagicMock(success=True, missing=False, error=None),
        MagicMock(success=False, missing=True, error=None),
    ]

    tasks.verify_s3_prefix("bucket", "data/", "org")

    mock_iter.assert_called_once_with("bucket", "data/")
    assert mock_verify.call_count == 2
