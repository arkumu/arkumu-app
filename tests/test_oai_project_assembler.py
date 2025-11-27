import pytest

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.services.oai_project_assembler import OAIProjectAssembler
from arkumu.projects import ProjectRecord, ProjectDigitalObject
from arkumu.projects.services.snapshot_service import ProjectSnapshotService
from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.users.models import Organization


class _DummyGraphService:
    """Minimal CanonicalGraphService stand-in for event graph hydration."""

    def __init__(self, event_graph):
        self._event_graph = event_graph

    def get_entity_graph(self, *args, **kwargs):
        return self._event_graph


@pytest.mark.django_db
def test_event_chain_applies_to_all_orgs():
    org = Organization.objects.create(name="FUK", code="fuk", is_active=True)
    project = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/digitales-objekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    event_id = "event-node"
    event_uri = "http://arkumu.org/data/fuk/entities/event/1"
    digital_path = "s3://bucket/object.tif"

    event_graph = {
        "root_id": event_id,
        "nodes": {
            event_id: {"uri": event_uri, "resource_type": ResourceType.ENTITY},
            str(digital.id): {"uri": digital.uri},
        },
        "edges": [
            {
                "subject_id": event_id,
                "predicate_canonical": ProjectSnapshotService.DIGITAL_OBJECT_LINK_URI,
                "object_id": str(digital.id),
            },
            {
                "subject_id": str(digital.id),
                "predicate_canonical": ProjectURIs.DIGITAL_OBJECT_PATH,
                "object_value": digital_path,
            },
        ],
    }

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        digital_objects=[],
        digital_object_sources={},
    )

    nodes = {
        str(project.id): {"uri": project.uri},
        event_id: {"uri": event_uri, "resource_type": ResourceType.ENTITY},
    }
    edges_by_subject = {
        str(project.id): [
            {
                "predicate_canonical": ProjectSnapshotService.EVENT_RELATION_URI,
                "object_id": event_id,
            }
        ],
        event_id: [],
    }
    graph = {"root_id": str(project.id)}

    assembler = OAIProjectAssembler(
        graph_service_factory=lambda **kwargs: _DummyGraphService(event_graph),
        snapshot_service=ProjectSnapshotService(),
    )

    updated = assembler._augment_shared_event_objects(
        record,
        nodes,
        edges_by_subject,
        graph,
        org_code="fuk",
    )

    assert updated is not None
    assert len(updated.digital_objects) == 1
    appended = updated.digital_objects[0]
    assert appended.resource_id == str(digital.id)
    assert appended.path == digital_path
    assert appended.source == "event"
    assert updated.harvestable is True


@pytest.mark.django_db
def test_event_chain_adds_missing_objects_even_when_other_media_present():
    org = Organization.objects.create(name="DET", code="det", is_active=True)
    project = Resource.objects.create(
        uri="http://arkumu.org/data/det/entities/projekt/1",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    digital = Resource.objects.create(
        uri="http://arkumu.org/data/det/entities/digitales-objekt/2",
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )

    existing_obj = ProjectDigitalObject(path="s3://bucket/direct.tif", uri="http://example.org/direct")
    existing_obj.resource_id = "1234"

    event_graph = {
        "root_id": "evt",
        "nodes": {
            "evt": {"uri": "http://arkumu.org/data/det/entities/event/1", "resource_type": ResourceType.ENTITY},
            str(digital.id): {"uri": digital.uri},
        },
        "edges": [
            {
                "subject_id": "evt",
                "predicate_canonical": ProjectSnapshotService.DIGITAL_OBJECT_LINK_URI,
                "object_id": str(digital.id),
            },
            {
                "subject_id": str(digital.id),
                "predicate_canonical": ProjectURIs.DIGITAL_OBJECT_PATH,
                "object_value": "s3://bucket/event-only.tif",
            },
        ],
    }

    record = ProjectRecord(
        subject_id=str(project.id),
        uri=project.uri,
        digital_objects=[existing_obj],
        digital_object_sources={"1234": {"source": "project", "via_project": True, "event_ids": [], "event_uris": []}},
    )

    nodes = {
        str(project.id): {"uri": project.uri},
        "evt": {"uri": "http://arkumu.org/data/det/entities/event/1", "resource_type": ResourceType.ENTITY},
    }
    edges_by_subject = {
        str(project.id): [
            {
                "predicate_canonical": ProjectSnapshotService.EVENT_RELATION_URI,
                "object_id": "evt",
            }
        ],
        "evt": [],
    }
    graph = {"root_id": str(project.id)}

    assembler = OAIProjectAssembler(
        graph_service_factory=lambda **kwargs: _DummyGraphService(event_graph),
        snapshot_service=ProjectSnapshotService(),
    )

    updated = assembler._augment_shared_event_objects(
        record,
        nodes,
        edges_by_subject,
        graph,
        org_code="det",
    )

    assert updated is not None
    assert len(updated.digital_objects) == 2
    event_obj = next(obj for obj in updated.digital_objects if obj.resource_id == str(digital.id))
    assert event_obj.path == "s3://bucket/event-only.tif"
    assert updated.digital_object_sources[str(digital.id)]["source"] == "event"
    # Running the augmentation again should not duplicate entries.
    second_pass = assembler._augment_shared_event_objects(
        updated,
        nodes,
        edges_by_subject,
        graph,
        org_code="det",
    )
    assert second_pass is not None
    assert len(second_pass.digital_objects) == 2
