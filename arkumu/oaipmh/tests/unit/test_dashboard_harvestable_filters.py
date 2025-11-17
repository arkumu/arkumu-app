"""Tests for curated harvestable filtering helpers."""

from __future__ import annotations

import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.dashboard_views import _is_s3_org, _s3_harvestable_project_ids
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.storage.models import S3FileObject
from arkumu.users.models import Organization


def _project(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


@pytest.mark.django_db
def test_is_s3_org_respects_settings(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ("fuk",)
    org = Organization.objects.create(name="FUK", code="fuk", domain="example.org", is_active=True)
    other = Organization.objects.create(name="KHM", code="khm", domain="example.org", is_active=True)

    assert _is_s3_org(org) is True
    assert _is_s3_org(other) is False


@pytest.mark.django_db
def test_s3_harvestable_project_ids_require_verified_s3(settings):
    settings.OAI_S3_HARVESTABLE_ORGS = ("fuk",)
    org = Organization.objects.create(name="FUK", code="fuk", domain="example.org", is_active=True)

    project_with_s3 = _project(org, "https://arkumu.org/entities/projekt/with-s3")
    project_without_s3 = _project(org, "https://arkumu.org/entities/projekt/without-s3")

    digital_with_s3 = _project(org, "https://arkumu.org/entities/digital/s3")
    digital_without_s3 = _project(org, "https://arkumu.org/entities/digital/no-s3")

    OAIProjectMediaLink.objects.create(
        project=project_with_s3,
        digital_object=digital_with_s3,
        status=OAIProjectMediaLink.STATUS_APPROVED,
    )
    OAIProjectMediaLink.objects.create(
        project=project_without_s3,
        digital_object=digital_without_s3,
        status=OAIProjectMediaLink.STATUS_APPROVED,
    )

    S3FileObject.objects.create(
        file_name="file.jpg",
        s3_key="fuk/data/file.jpg",
        organization="fuk",
        status="verified",
        related_resource=digital_with_s3,
    )

    ids = _s3_harvestable_project_ids(org)

    assert ids == {project_with_s3.id}
