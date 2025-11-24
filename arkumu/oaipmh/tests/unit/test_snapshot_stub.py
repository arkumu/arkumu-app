from __future__ import annotations

from typing import Optional

import pytest

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.services.snapshot_stub import InMemorySnapshotService, build_db_backed_record
from arkumu.projects import ProjectRecord


@pytest.mark.django_db
def test_snapshot_stub_builds_records_with_custom_builder():
    resource = Resource.objects.create(
        uri="http://example.org/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
    )

    def builder(res: Resource) -> Optional[ProjectRecord]:
        return ProjectRecord(subject_id=str(res.id), uri=res.uri, digital_objects=[])

    service = InMemorySnapshotService(record_builder=builder, harvestable_statuses=None)
    snapshot = service.get_cross_institutional_snapshot()

    assert snapshot is not None
    assert len(snapshot.projects) == 1
    assert snapshot.projects[0].uri == resource.uri


@pytest.mark.django_db
def test_snapshot_stub_get_record_by_uri_uses_index():
    resource = Resource.objects.create(
        uri="http://example.org/entities/projekt/2",
        resource_type=ResourceType.ENTITY,
    )

    service = InMemorySnapshotService(
        record_builder=lambda res: ProjectRecord(subject_id=str(res.id), uri=res.uri, digital_objects=[]),
        harvestable_statuses=None,
    )
    service.get_cross_institutional_snapshot()

    record = service.get_record_by_uri(resource.uri)
    assert record is not None
    assert record.uri == resource.uri

