import io

import pytest
from django.core.management import call_command

from arkumu.storage.models import S3FileObject


@pytest.mark.django_db
def test_inspect_s3_key_formats_reports_missing_prefixes():
    S3FileObject.objects.create(
        file_name="prefixed.jpg",
        s3_key="s3://bucket-a/prefixed.jpg",
        status="verified",
        organization="bucket-a",
    )
    missing = S3FileObject.objects.create(
        file_name="unprefixed.jpg",
        s3_key="folder/unprefixed.jpg",
        status="pending",
        organization="",
    )

    out = io.StringIO()
    call_command("inspect_s3_key_formats", stdout=out)

    output = out.getvalue()
    assert "With full 's3://bucket/key' prefix: 1" in output
    assert "Without prefix: 1" in output
    assert missing.s3_key in output
