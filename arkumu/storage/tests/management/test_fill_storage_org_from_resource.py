import io

import pytest
from django.core.management import call_command

from arkumu.metadata.models.resource import (
    PublicAccessLevel,
    Resource,
    ResourceType,
)
from arkumu.storage.models import S3FileObject
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_command_updates_missing_storage_org():
    org = Organization.objects.create(name="Detmold", code="det")
    resource = Resource.objects.create(
        uri="http://arkumu.org/data/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    file_obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/det/file.txt",
        organization="",
        related_resource=resource,
    )

    out = io.StringIO()
    call_command("fill_storage_org_from_resource", stdout=out)

    file_obj.refresh_from_db()
    assert file_obj.organization == "det"
    assert "Updated 1 row(s)" in out.getvalue()


@pytest.mark.django_db
def test_command_respects_dry_run():
    org = Organization.objects.create(name="RSH", code="rsh")
    resource = Resource.objects.create(
        uri="http://arkumu.org/data/entities/projekt/2",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    file_obj = S3FileObject.objects.create(
        file_name="file.txt",
        s3_key="data/rsh/file.txt",
        organization="",
        related_resource=resource,
    )

    out = io.StringIO()
    call_command("fill_storage_org_from_resource", "--dry-run", stdout=out)

    file_obj.refresh_from_db()
    assert file_obj.organization == ""
    assert "[dry-run]" in out.getvalue()


@pytest.mark.django_db
def test_command_filters_by_organization():
    det = Organization.objects.create(name="Detmold", code="det")
    rsh = Organization.objects.create(name="Robert Schumann", code="rsh")
    det_resource = Resource.objects.create(
        uri="http://arkumu.org/data/entities/projekt/3",
        resource_type=ResourceType.ENTITY,
        organization=det,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    rsh_resource = Resource.objects.create(
        uri="http://arkumu.org/data/entities/projekt/4",
        resource_type=ResourceType.ENTITY,
        organization=rsh,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    det_file = S3FileObject.objects.create(
        file_name="det.txt",
        s3_key="data/det/file.txt",
        organization="",
        related_resource=det_resource,
    )
    rsh_file = S3FileObject.objects.create(
        file_name="rsh.txt",
        s3_key="data/rsh/file.txt",
        organization="",
        related_resource=rsh_resource,
    )

    call_command("fill_storage_org_from_resource", "--organization", "det")

    det_file.refresh_from_db()
    rsh_file.refresh_from_db()
    assert det_file.organization == "det"
    assert rsh_file.organization == ""
