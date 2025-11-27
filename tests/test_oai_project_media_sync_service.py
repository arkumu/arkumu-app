import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.oaipmh.services.oai_project_media_sync_service import (
    OAIProjectMediaSyncService,
)
from arkumu.projects import ProjectDigitalObject, ProjectRecord
from arkumu.users.models import Organization


class _AssemblerStub:
    def __init__(self, record: ProjectRecord) -> None:
        self._record = record

    def build_record(self, context):
        return self._record


@pytest.mark.django_db
def test_sync_preserves_links_when_only_paths_match(monkeypatch):
    org = Organization.objects.create(code="fuk", name="FUK", is_active=True)
    project = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/digitales-objekt/8184",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        value="s3://bucket/portrait_twitter.tif",
    )
    link = OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital,
        is_stale=True,
    )

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        digital_objects=[
            ProjectDigitalObject(
                path="s3://bucket/portrait_twitter.tif",
                source="event",
            )
        ],
    )

    service = OAIProjectMediaSyncService(assembler=_AssemblerStub(record))
    monkeypatch.setattr(service, "_resources_by_id", lambda ids: {})
    monkeypatch.setattr(service, "_resources_by_uri", lambda uris: {})

    result = service.sync_project(project)

    link.refresh_from_db()
    assert result.stale == 0
    assert result.created == 0
    assert result.refreshed == 1
    assert OAIProjectMediaLink.objects.filter(project=project).count() == 1
    assert link.is_stale is False
    assert link.source == OAIProjectMediaLink.SOURCE_EVENT
