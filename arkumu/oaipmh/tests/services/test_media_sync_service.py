"""Unit tests for :mod:`arkumu.oaipmh.services.oai_project_media_sync_service`."""

from __future__ import annotations

import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.oaipmh.services import OAIProjectMediaSyncService
from arkumu.projects import ProjectDigitalObject, ProjectRecord
from arkumu.users.models import Organization


class _StubAssembler:
    """Deterministic assembler for sync-service tests."""

    def __init__(self, record: ProjectRecord | None) -> None:
        self._record = record

    def build_record(self, _context):
        return self._record


def _project_resource(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


def _digital_resource(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


@pytest.mark.django_db
def test_sync_creates_pending_links_from_record():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _project_resource(org, "http://arkumu.test/entities/projekt/1")
    digital = _digital_resource(org, "http://arkumu.test/entities/digital/1")

    digital_object = ProjectDigitalObject(path="s3://bucket/file.jpg", uri=digital.uri)
    digital_object.resource_id = str(digital.id)
    digital_object.source = "event"

    record = ProjectRecord(subject_id=str(project.id), uri=project.uri, digital_objects=[digital_object])
    service = OAIProjectMediaSyncService(assembler=_StubAssembler(record))

    result = service.sync_project(project)

    assert result.created == 1
    assert result.refreshed == 0
    assert result.stale == 0

    link = OAIProjectMediaLink.objects.get(project=project, digital_object=digital)
    assert link.source == OAIProjectMediaLink.SOURCE_EVENT
    assert link.is_stale is False
    assert link.order_index == 1


@pytest.mark.django_db
def test_sync_uses_provided_record_when_supplied(monkeypatch):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _project_resource(org, "http://arkumu.test/entities/projekt/99")
    digital = _digital_resource(org, "http://arkumu.test/entities/digital/99")

    digital_object = ProjectDigitalObject(path="s3://bucket/file-99.jpg", uri=digital.uri)
    digital_object.resource_id = str(digital.id)
    digital_object.source = "event"

    record = ProjectRecord(subject_id=str(project.id), uri=project.uri, digital_objects=[digital_object])

    def _explode(self, _project):
        raise AssertionError("Assembler should not be invoked when record is provided")

    monkeypatch.setattr(OAIProjectMediaSyncService, "_assemble_record", _explode)

    service = OAIProjectMediaSyncService(assembler=_StubAssembler(None))

    result = service.sync_project(project, record=record)

    assert result.created == 1
    assert OAIProjectMediaLink.objects.filter(project=project, digital_object=digital).exists()


@pytest.mark.django_db
def test_sync_updates_existing_links_and_clears_stale():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _project_resource(org, "http://arkumu.test/entities/projekt/2")
    digital = _digital_resource(org, "http://arkumu.test/entities/digital/2")

    link = OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital,
        source=OAIProjectMediaLink.SOURCE_UNKNOWN,
        is_stale=True,
        order_index=3,
    )

    digital_object = ProjectDigitalObject(path="s3://bucket/file-2.jpg", uri=digital.uri)
    digital_object.resource_id = str(digital.id)
    digital_object.source = "project+event"

    record = ProjectRecord(subject_id=str(project.id), uri=project.uri, digital_objects=[digital_object])
    service = OAIProjectMediaSyncService(assembler=_StubAssembler(record))

    result = service.sync_project(project)

    link.refresh_from_db()
    assert result.created == 0
    assert result.refreshed == 1
    assert result.stale == 0
    assert link.source == OAIProjectMediaLink.SOURCE_PROJECT
    assert link.is_stale is False
    # Manual order should remain untouched
    assert link.order_index == 3


@pytest.mark.django_db
def test_sync_marks_missing_approved_links_stale():
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _project_resource(org, "http://arkumu.test/entities/projekt/3")
    digital = _digital_resource(org, "http://arkumu.test/entities/digital/3")

    link = OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital,
        source=OAIProjectMediaLink.SOURCE_PROJECT,
        is_stale=False,
    )

    empty_record = ProjectRecord(subject_id=str(project.id), uri=project.uri, digital_objects=[])
    service = OAIProjectMediaSyncService(assembler=_StubAssembler(empty_record))

    result = service.sync_project(project)

    link.refresh_from_db()
    assert result.created == 0
    assert result.refreshed == 0
    assert result.stale == 1
    assert link.is_stale is True
