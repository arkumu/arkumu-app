import io

import pytest
from django.core.management import call_command, CommandError

from arkumu.storage.models import S3FileObject
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel


def _make_resource(org: Organization, idx: int) -> Resource:
    return Resource.objects.create(
        uri=f"http://arkumu.org/data/entities/projekt/{idx}",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )


@pytest.mark.django_db
def test_promote_updates_matching_rows():
    org = Organization.objects.create(name="Detmold", code="det")
    resource = _make_resource(org, 1)
    file_pending = S3FileObject.objects.create(
        file_name="pending.txt",
        s3_key="data/det/pending.txt",
        organization="det",
        status="pending",
        related_resource=resource,
    )
    file_completed = S3FileObject.objects.create(
        file_name="completed.txt",
        s3_key="data/det/completed.txt",
        organization="det",
        status="completed",
        related_resource=resource,
    )

    call_command("promote_s3_status", "--organization", "det")

    file_pending.refresh_from_db()
    file_completed.refresh_from_db()
    assert file_pending.status == "verified"
    assert file_completed.status == "verified"


@pytest.mark.django_db
def test_promote_dry_run_does_not_mutate():
    org = Organization.objects.create(name="RSH", code="rsh")
    resource = _make_resource(org, 2)
    file_obj = S3FileObject.objects.create(
        file_name="uploading.txt",
        s3_key="data/rsh/uploading.txt",
        organization="rsh",
        status="uploading",
        related_resource=resource,
    )

    out = io.StringIO()
    call_command("promote_s3_status", "--organization", "rsh", "--dry-run", stdout=out)

    file_obj.refresh_from_db()
    assert file_obj.status == "uploading"
    assert "[dry-run]" in out.getvalue()


@pytest.mark.django_db
def test_promote_custom_source_status_and_target():
    org = Organization.objects.create(name="FUK", code="fuk")
    resource = _make_resource(org, 3)
    file_failed = S3FileObject.objects.create(
        file_name="failed.txt",
        s3_key="data/fuk/failed.txt",
        organization="fuk",
        status="failed",
        related_resource=resource,
    )

    call_command(
        "promote_s3_status",
        "--organization",
        "fuk",
        "--include-status",
        "failed",
        "--target-status",
        "completed",
    )

    file_failed.refresh_from_db()
    assert file_failed.status == "completed"


@pytest.mark.django_db
def test_promote_rejects_invalid_status():
    with pytest.raises(CommandError):
        call_command("promote_s3_status", "--target-status", "unknown")
