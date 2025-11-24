import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh.media_link_views import (
    PROJECT_DIGITAL_PREDICATE_URI,
    PROJECT_RELATION_PREDICATE_URI,
    _run_media_link_seed,
)
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.users.models import Organization


def _property_resource(uri: str, canonical: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        canonical_uri=canonical,
        resource_type=ResourceType.PROPERTY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


def _project_resource(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


def _digital_resource(org: Organization, uri: str, value: str = "") -> Resource:
    return Resource.objects.create(
        uri=uri,
        value=value,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


@pytest.mark.django_db
def test_seed_creates_links_from_direct_project_relation():
    org = Organization.objects.create(code="khm", name="KHM", is_active=True)
    project = _project_resource(org, "http://arkumu.org/data/khm/entities/projekt/1")
    digital = _digital_resource(org, "http://arkumu.org/data/khm/entities/digital/1", value="s3://bucket/file-1.tif")
    predicate = _property_resource(
        "http://arkumu.org/data/khm/properties/digital-object",
        PROJECT_DIGITAL_PREDICATE_URI,
    )

    Triple.objects.create(subject=project, predicate=predicate, object=digital, source=org)

    summary = _run_media_link_seed(org)

    assert summary["created"] == 1
    link = OAIProjectMediaLink.objects.get(project=project, digital_object=digital)
    assert link.source == OAIProjectMediaLink.SOURCE_PROJECT
    assert link.is_stale is False


@pytest.mark.django_db
def test_seed_creates_links_from_event_bridge():
    org = Organization.objects.create(code="hmt", name="HMT", is_active=True)
    project = _project_resource(org, "http://arkumu.org/data/hmt/entities/projekt/7")
    digital = _digital_resource(org, "http://arkumu.org/data/hmt/entities/digital/9", value="s3://bucket/event-file.wav")
    event = _project_resource(org, "http://arkumu.org/data/hmt/entities/ereignis/3")

    project_predicate = _property_resource(
        "http://arkumu.org/data/hmt/properties/projekt-link",
        PROJECT_RELATION_PREDICATE_URI,
    )
    digital_predicate = _property_resource(
        "http://arkumu.org/data/hmt/properties/digitalesobjekt-id-fk",
        PROJECT_DIGITAL_PREDICATE_URI,
    )

    Triple.objects.create(subject=event, predicate=project_predicate, object=project, source=org)
    Triple.objects.create(subject=event, predicate=digital_predicate, object=digital, source=org)

    summary = _run_media_link_seed(org)

    assert summary["created"] == 1
    link = OAIProjectMediaLink.objects.get(project=project, digital_object=digital)
    assert link.source == OAIProjectMediaLink.SOURCE_EVENT
    assert link.is_stale is False


@pytest.mark.django_db
def test_seed_marks_missing_links_stale():
    org = Organization.objects.create(code="det", name="DET", is_active=True)
    project = _project_resource(org, "http://arkumu.org/data/det/entities/projekt/11")
    digital = _digital_resource(org, "http://arkumu.org/data/det/entities/digital/11")
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital)

    summary = _run_media_link_seed(org)

    link = OAIProjectMediaLink.objects.get(project=project, digital_object=digital)
    assert link.is_stale is True
    assert summary["stale"] == 1
