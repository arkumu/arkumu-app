import pytest
from types import SimpleNamespace

from arkumu.common.uri_utils import mint_uri, slugify_uri_part
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization


class _StubSchemaService:
    def __init__(self, datasets):
        self._datasets = datasets
        self._processor = SimpleNamespace()

    def list_datasets(self):
        return list(self._datasets.keys())

    def get_dataset_schema(self, dataset_name):
        return self._datasets.get(dataset_name)

    def _ensure_schema_loaded(self):
        return None


def _make_join_schema(
    *,
    organization,
    join_dataset: str,
    project_dataset: str,
    event_dataset: str,
    project_property_uri: str,
    event_property_uri: str,
):
    join_class = Resource.objects.create(
        uri=f"http://example.org/types/{join_dataset}",
        resource_type=ResourceType.CLASS,
        name=f"{join_dataset}_Type",
        organization=organization,
    )

    project_property, _ = Resource.objects.get_or_create(
        uri=project_property_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "project_fk",
            "organization": organization,
        },
    )
    event_property, _ = Resource.objects.get_or_create(
        uri=event_property_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "event_fk",
            "organization": organization,
        },
    )

    return {
        "entity_type": join_class,
        "properties": {
            "project_fk": project_property,
            "event_fk": event_property,
        },
        "column_metadata": {},
        "anchor_columns": [],
        "fk_relationships": [
            {
                "source_column": "project_fk",
                "target_dataset": project_dataset,
                "source_property_uri": project_property_uri,
            },
            {
                "source_column": "event_fk",
                "target_dataset": event_dataset,
                "source_property_uri": event_property_uri,
            },
        ],
    }


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="stuborg", name="Stub Org")


@pytest.fixture
def mapping(db, organization):
    return Mapping.objects.create(name="Stub Mapping", organization_id=organization.code)


@pytest.mark.django_db
def test_dataset_summary_counts_entities_when_blueprint_lacks_resource(
    monkeypatch,
    organization,
    mapping,
):
    dataset_name = "Dataset_One"
    schema_blueprint = {
        dataset_name: {
            "entity_type": SimpleNamespace(name="Dataset One"),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        }
    }
    stub_service = _StubSchemaService(schema_blueprint)

    def _stub_schema_service(**kwargs):
        return stub_service

    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        lambda **kwargs: stub_service,
    )

    service = SchemaWorkspaceService(mapping=mapping, organization=organization)

    dataset_uri = mint_uri(
        "http://arkumu.org/data",
        slugify_uri_part(organization.code),
        "datasets",
        slugify_uri_part(dataset_name),
    )
    dataset_resource = Resource.objects.create(
        uri=dataset_uri,
        resource_type=ResourceType.IRI,
        organization=organization,
        name="Dataset One",
    )
    entity_resource = Resource.objects.create(
        uri="http://example.org/entity/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    is_part_of, _ = Resource.objects.get_or_create(
        uri="http://purl.org/dc/terms/isPartOf",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "isPartOf",
            "organization": organization,
        },
    )
    Triple.objects.create(
        subject=entity_resource,
        predicate=is_part_of,
        object=dataset_resource,
        source=organization,
    )

    summary = service.get_dataset_summary(dataset_name)
    assert summary.entity_count == 1

    dataset_listing = service.list_datasets()
    assert dataset_listing[0].entity_count == 1


@pytest.mark.django_db
def test_list_join_relationships_and_sync(monkeypatch, organization, mapping):
    project_dataset = "Projekt"
    event_dataset = "Ereignis"
    join_dataset = "Projekt_Ereignis"
    project_property_uri = "http://arkumu.org/data/properties/projekt"
    event_property_uri = "http://arkumu.org/data/properties/ereignis"

    join_schema = _make_join_schema(
        organization=organization,
        join_dataset=join_dataset,
        project_dataset=project_dataset,
        event_dataset=event_dataset,
        project_property_uri=project_property_uri,
        event_property_uri=event_property_uri,
    )

    schema_blueprint = {
        project_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/projekt",
                resource_type=ResourceType.CLASS,
                name="Projekt",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        event_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/ereignis",
                resource_type=ResourceType.CLASS,
                name="Ereignis",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        join_dataset: join_schema,
    }

    stub_service = _StubSchemaService(schema_blueprint)

    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        lambda **kwargs: stub_service,
    )

    service = SchemaWorkspaceService(mapping=mapping, organization=organization)

    relationships = service.list_join_relationships(project_dataset)
    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship.other_dataset == event_dataset

    project_resource = Resource.objects.create(
        uri="http://example.org/project/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    event_resource = Resource.objects.create(
        uri="http://example.org/event/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    # Prepare dataset resource for join entities
    join_dataset_uri = mint_uri(
        service.base_uri,
        slugify_uri_part(organization.code),
        "datasets",
        slugify_uri_part(join_dataset),
    )
    Resource.objects.get_or_create(
        uri=join_dataset_uri,
        defaults={
            "resource_type": ResourceType.IRI,
            "name": join_dataset,
            "organization": organization,
        },
    )

    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
            "organization": organization,
        },
    )

    service.sync_join_relationship(
        entity_uri=project_resource.uri,
        relationship=relationship,
        related_items=[{"uri": event_resource.uri, "context": {}}],
    )

    project_property = Resource.objects.get(uri=project_property_uri)
    event_property = Resource.objects.get(uri=event_property_uri)

    join_subject_ids = Triple.objects.filter(
        predicate=project_property,
        object=project_resource,
    ).values_list("subject_id", flat=True)

    assert join_subject_ids
    join_subject_id = join_subject_ids[0]

    assert Triple.objects.filter(
        subject_id=join_subject_id,
        predicate=event_property,
        object=event_resource,
    ).exists()

    # Remove relationship and ensure join entity is deleted
    service.sync_join_relationship(
        entity_uri=project_resource.uri,
        relationship=relationship,
        related_items=[],
    )

    assert not Triple.objects.filter(
        predicate=project_property,
        object=project_resource,
    ).exists()


@pytest.mark.django_db
def test_list_join_relationships_ignores_non_junction_fk_datasets(monkeypatch, organization, mapping):
    project_dataset = "Projekt"
    event_dataset = "Ereignis"
    digital_dataset = "Digitales Objekt"
    child_dataset = "Produktionsereignis"
    join_dataset = "Projekt_Ereignis"

    project_property_uri = "http://example.org/properties/join-projekt"
    event_property_uri = "http://example.org/properties/join-ereignis"
    digital_property_uri = "http://example.org/properties/join-digital"

    child_anchor = Resource.objects.create(
        uri="http://example.org/properties/child-id",
        resource_type=ResourceType.PROPERTY,
        name="child_id",
        organization=organization,
    )
    child_project_property = Resource.objects.create(
        uri=project_property_uri,
        resource_type=ResourceType.PROPERTY,
        name="project_fk",
        organization=organization,
    )
    child_digital_property = Resource.objects.create(
        uri=digital_property_uri,
        resource_type=ResourceType.PROPERTY,
        name="digital_fk",
        organization=organization,
    )

    join_schema = _make_join_schema(
        organization=organization,
        join_dataset=join_dataset,
        project_dataset=project_dataset,
        event_dataset=event_dataset,
        project_property_uri=project_property_uri,
        event_property_uri=event_property_uri,
    )

    schema_blueprint = {
        project_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/projekt-main",
                resource_type=ResourceType.CLASS,
                name="Projekt",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        event_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/ereignis-main",
                resource_type=ResourceType.CLASS,
                name="Ereignis",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        digital_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/digital-main",
                resource_type=ResourceType.CLASS,
                name="Digitales Objekt",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        child_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/child-main",
                resource_type=ResourceType.CLASS,
                name="Produktionsereignis",
                organization=organization,
            ),
            "properties": {
                "child_id": child_anchor,
                "project_fk": child_project_property,
                "digital_fk": child_digital_property,
            },
            "column_metadata": {
                "child_id": {"column_type": "text", "is_anchor": True},
                "project_fk": {"column_type": "fk"},
                "digital_fk": {"column_type": "fk"},
            },
            "anchor_columns": [{"column_name": "child_id"}],
            "fk_relationships": [
                {
                    "source_column": "project_fk",
                    "target_dataset": project_dataset,
                    "source_property_uri": project_property_uri,
                },
                {
                    "source_column": "digital_fk",
                    "target_dataset": digital_dataset,
                    "source_property_uri": digital_property_uri,
                },
            ],
        },
        join_dataset: join_schema,
    }

    stub_service = _StubSchemaService(schema_blueprint)
    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        lambda **kwargs: stub_service,
    )

    service = SchemaWorkspaceService(mapping=mapping, organization=organization)

    relationships = service.list_join_relationships(project_dataset)

    assert len(relationships) == 1
    assert relationships[0].join_dataset == join_dataset
    assert relationships[0].other_dataset == event_dataset


@pytest.mark.django_db
def test_list_join_relationships_ignores_unrelated_inferred_junctions(monkeypatch, organization, mapping):
    project_dataset = "Projekt"
    event_dataset = "Ereignis"
    digital_dataset = "Digitales Objekt"
    related_join_dataset = "Projekt_Ereignis"
    unrelated_join_dataset = "Ereignis_Digitales_Objekt"

    project_property_uri = "http://example.org/properties/related-projekt"
    event_property_uri = "http://example.org/properties/related-ereignis"
    digital_property_uri = "http://example.org/properties/related-digital"

    related_join_schema = _make_join_schema(
        organization=organization,
        join_dataset=related_join_dataset,
        project_dataset=project_dataset,
        event_dataset=event_dataset,
        project_property_uri=project_property_uri,
        event_property_uri=event_property_uri,
    )

    unrelated_join_class = Resource.objects.create(
        uri=f"http://example.org/types/{unrelated_join_dataset}",
        resource_type=ResourceType.CLASS,
        name=unrelated_join_dataset,
        organization=organization,
    )
    unrelated_event_property, _ = Resource.objects.get_or_create(
        uri=event_property_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "event_fk",
            "organization": organization,
        },
    )
    unrelated_digital_property, _ = Resource.objects.get_or_create(
        uri=digital_property_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "digital_fk",
            "organization": organization,
        },
    )

    schema_blueprint = {
        project_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/projekt-related",
                resource_type=ResourceType.CLASS,
                name="Projekt",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        event_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/ereignis-related",
                resource_type=ResourceType.CLASS,
                name="Ereignis",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        digital_dataset: {
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/digital-related",
                resource_type=ResourceType.CLASS,
                name="Digitales Objekt",
                organization=organization,
            ),
            "properties": {},
            "column_metadata": {},
            "anchor_columns": [],
            "fk_relationships": [],
        },
        related_join_dataset: related_join_schema,
        unrelated_join_dataset: {
            "entity_type": unrelated_join_class,
            "properties": {
                "event_fk": unrelated_event_property,
                "digital_fk": unrelated_digital_property,
            },
            "column_metadata": {
                "event_fk": {"column_type": "fk"},
                "digital_fk": {"column_type": "fk"},
            },
            "anchor_columns": [],
            "fk_relationships": [
                {
                    "source_column": "event_fk",
                    "target_dataset": event_dataset,
                    "source_property_uri": event_property_uri,
                },
                {
                    "source_column": "digital_fk",
                    "target_dataset": digital_dataset,
                    "source_property_uri": digital_property_uri,
                },
            ],
        },
    }

    stub_service = _StubSchemaService(schema_blueprint)
    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        lambda **kwargs: stub_service,
    )

    service = SchemaWorkspaceService(mapping=mapping, organization=organization)

    relationships = service.list_join_relationships(project_dataset)

    assert len(relationships) == 1
    assert relationships[0].join_dataset == related_join_dataset
    assert relationships[0].other_dataset == event_dataset
