from unittest.mock import patch

import pytest
from django.core.management import call_command, CommandError


@pytest.mark.django_db
def test_recalculate_checksums_invokes_task_with_defaults():
    with patch("arkumu.storage.management.commands.recalculate_s3_checksums.recalculate_s3_checksums") as mock_task:
        call_command("recalculate_s3_checksums")

    mock_task.assert_called_once_with(organization=None, missing_only=True, limit=None)


@pytest.mark.django_db
def test_recalculate_checksums_with_options():
    with patch("arkumu.storage.management.commands.recalculate_s3_checksums.recalculate_s3_checksums") as mock_task:
        call_command(
            "recalculate_s3_checksums",
            "--bucket",
            "rsh",
            "--all",
            "--limit",
            "25",
        )

    mock_task.assert_called_once_with(
        organization="rsh",
        missing_only=False,
        limit=25,
    )


@pytest.mark.django_db
def test_recalculate_checksums_wraps_exceptions():
    with patch(
        "arkumu.storage.management.commands.recalculate_s3_checksums.recalculate_s3_checksums",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(CommandError):
            call_command("recalculate_s3_checksums")
