import json
from types import SimpleNamespace
from typing import Dict

import pytest

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.schema_workspace.forms import DatasetEntityForm
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService
from arkumu.metadata.views.schema_workspace_views import (
    _apply_relationship_initials,
    _remove_join_source_fields,
)
from arkumu.users.models import Organization


class _StubSchemaService:
    def __init__(self, datasets: Dict[str, Dict]):
        self._datasets = datasets
        self._processor = SimpleNamespace()

    def list_datasets(self):
        return list(self._datasets.keys())

    def get_dataset_schema(self, dataset_name):
        return self._datasets.get(dataset_name)

    def _ensure_schema_loaded(self):
        return None


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="stub", name="Stub Org")


@pytest.fixture
def mapping(db, organization):
    return Mapping.objects.create(
        name="Stub Mapping",
        organization_id=organization.code,
        mapping_config={},
    )


@pytest.fixture
def workspace_setup(monkeypatch, organization, mapping):
    project_class = Resource.objects.create(
        uri="http://example.org/types/projekt",
        resource_type=ResourceType.CLASS,
        organization=organization,
        name="Projekt",
    )
    event_class = Resource.objects.create(
        uri="http://example.org/types/ereignis",
        resource_type=ResourceType.CLASS,
        organization=organization,
        name="Ereignis",
    )
    actor_class = Resource.objects.create(
        uri="http://example.org/types/akteur",
        resource_type=ResourceType.CLASS,
        organization=organization,
        name="Akteurin",
    )
    join_class = Resource.objects.create(
        uri="http://example.org/types/projekt-ereignis",
        resource_type=ResourceType.CLASS,
        organization=organization,
        name="ProjektEreignis",
    )

    projekt_dataset_resource = Resource.objects.create(
        uri="http://example.org/datasets/projekt",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Projekt Dataset",
    )
    ereignis_dataset_resource = Resource.objects.create(
        uri="http://example.org/datasets/ereignis",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Ereignis Dataset",
    )

    anchor_property = Resource.objects.create(
        uri="http://example.org/properties/projekt-id",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="projekt_id",
    )
    actor_property = Resource.objects.create(
        uri="http://example.org/properties/actor",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Akteur",
    )
    event_property = Resource.objects.create(
        uri="http://example.org/properties/event",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Ereignis",
    )
    event_name_property = Resource.objects.create(
        uri="http://example.org/properties/event_name",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Event Name",
    )
    project_fk_property = Resource.objects.create(
        uri="http://example.org/properties/project_fk",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Projekt FK",
    )
    event_fk_property = Resource.objects.create(
        uri="http://example.org/properties/event_fk",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Ereignis FK",
    )

    projekt_schema = {
        "entity_type": project_class,
        "properties": {
            "projekt_id": anchor_property,
            "actor_refs": actor_property,
            "event_refs": event_property,
        },
        "dataset_resource": projekt_dataset_resource,
        "column_metadata": {
            "projekt_id": {"column_type": "text", "is_anchor": True},
            "actor_refs": {"column_type": "fk", "is_multi_value": True},
            "event_refs": {"column_type": "fk", "is_multi_value": True},
        },
        "anchor_columns": [{"column_name": "projekt_id"}],
        "fk_relationships": [
            {
                "source_column": "actor_refs",
                "target_dataset": "Akteurin",
                "source_property_uri": actor_property.uri,
            },
            {
                "source_column": "event_refs",
                "target_dataset": "Ereignis",
                "source_property_uri": event_property.uri,
            }
        ],
    }

    ereignis_schema = {
        "entity_type": event_class,
        "properties": {
            "event_name": event_name_property,
        },
        "dataset_resource": ereignis_dataset_resource,
        "column_metadata": {
            "event_name": {"column_type": "text", "is_multi_value": False},
        },
        "anchor_columns": [],
        "fk_relationships": [],
    }

    akteurin_schema = {
        "entity_type": actor_class,
        "properties": {},
        "column_metadata": {},
        "anchor_columns": [],
        "fk_relationships": [],
    }

    join_schema = {
        "entity_type": join_class,
        "properties": {
            "project_fk": project_fk_property,
            "event_fk": event_fk_property,
        },
        "column_metadata": {
            "project_fk": {"column_type": "fk"},
            "event_fk": {"column_type": "fk"},
        },
        "anchor_columns": [],
        "fk_relationships": [
            {
                "source_column": "project_fk",
                "target_dataset": "Projekt",
                "source_property_uri": project_fk_property.uri,
            },
            {
                "source_column": "event_fk",
                "target_dataset": "Ereignis",
                "source_property_uri": event_fk_property.uri,
            },
        ],
        "junction_schema": {
            "primary_dataset": "Projekt",
            "secondary_dataset": "Ereignis",
            "primary_fk": "project_fk",
            "secondary_fk": "event_fk",
            "context_columns": [],
        },
    }

    datasets = {
        "Projekt": projekt_schema,
        "Ereignis": ereignis_schema,
        "Akteurin": akteurin_schema,
        "Projekt_Ereignis": join_schema,
    }

    stub_service = _StubSchemaService(datasets)
    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        lambda **_: stub_service,
    )

    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "organization": organization,
            "name": "rdf:type",
        },
    )
    Resource.objects.get_or_create(
        uri="http://purl.org/dc/terms/isPartOf",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "organization": organization,
            "name": "isPartOf",
        },
    )

    service = SchemaWorkspaceService(mapping=mapping, organization=organization)
    return {
        "service": service,
        "actor_property": actor_property,
        "event_property": event_property,
        "organization": organization,
    }


@pytest.mark.django_db
def test_list_join_relationships_handles_junction_schema(workspace_setup):
    service = workspace_setup["service"]

    relationships = service.list_join_relationships("Projekt")
    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship.other_dataset == "Ereignis"
    assert relationship.self_column == "project_fk"
    assert relationship.other_property_uri.endswith("event_fk")


@pytest.mark.django_db
def test_list_join_relationships_uses_configured_widget(workspace_setup):
    service = workspace_setup["service"]
    mapping = service.mapping
    mapping.mapping_config = {
        "junction_widgets": {
            "Projekt": [
                {
                    "widget": "JunctionRelationshipWidget",
                    "join_dataset": "Projekt_Ereignis",
                    "self_column": "project_fk",
                    "other_column": "event_fk",
                    "other_dataset": "Ereignis",
                    "search_columns": ["event_name"],
                }
            ]
        }
    }

    relationships = service.list_join_relationships("Projekt")
    assert len(relationships) == 1
    relationship = relationships[0]
    assert relationship.widget_name == "JunctionRelationshipWidget"
    assert relationship.search_property_uris == ["http://example.org/properties/event_name"]

    field_metadata = service.get_field_metadata("Projekt")
    metadata, join_map = service.augment_field_metadata_with_joins("Projekt", field_metadata)
    field_name = "__join__Projekt_Ereignis__Ereignis"
    assert field_name in metadata
    assert metadata[field_name]["selected_property"] == "http://example.org/properties/event_name"
    assert metadata[field_name]["search_property_uris"] == ["http://example.org/properties/event_name"]
    assert metadata[field_name]["widget"] == "JunctionRelationshipWidget"
    assert join_map[field_name] == relationship


@pytest.mark.django_db
def test_collect_relationship_values_includes_join_and_fk(workspace_setup):
    service = workspace_setup["service"]
    organization = workspace_setup["organization"]

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
    actor_resource = Resource.objects.create(
        uri="http://example.org/actor/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    Triple.objects.create(
        subject=project_resource,
        predicate=workspace_setup["actor_property"],
        object=actor_resource,
        source=organization,
    )
    Triple.objects.create(
        subject=project_resource,
        predicate=workspace_setup["event_property"],
        object=event_resource,
        source=organization,
    )

    field_metadata = service.get_field_metadata("Projekt")
    field_metadata, join_field_map = service.augment_field_metadata_with_joins(
        "Projekt",
        field_metadata,
    )

    relationship_values = service.collect_relationship_values(
        dataset_name="Projekt",
        entity_uri=project_resource.uri,
        field_metadata=field_metadata,
        join_field_map=join_field_map,
    )

    assert len(relationship_values) == 2
    event_values = next(
        rel for rel in relationship_values if not rel.is_join and rel.target_dataset == "Ereignis"
    )
    direct_values = next(
        rel for rel in relationship_values if not rel.is_join and rel.target_dataset == "Akteurin"
    )

    assert event_values.uris == [event_resource.uri]
    assert direct_values.uris == [actor_resource.uri]

    event_field_metadata = service.get_field_metadata("Ereignis")
    event_field_metadata, event_join_map = service.augment_field_metadata_with_joins(
        "Ereignis",
        event_field_metadata,
    )
    event_relationship_values = service.collect_relationship_values(
        dataset_name="Ereignis",
        entity_uri=event_resource.uri,
        field_metadata=event_field_metadata,
        join_field_map=event_join_map,
    )

    reverse_values = next(
        rel for rel in event_relationship_values if rel.target_dataset == "Projekt"
    )
    assert project_resource.uri in reverse_values.uris


@pytest.mark.django_db
def test_apply_relationship_initials_respects_mutate_flag(workspace_setup):
    service = workspace_setup["service"]
    organization = workspace_setup["organization"]

    project_resource = Resource.objects.create(
        uri="http://example.org/project/2",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    actor_resource = Resource.objects.create(
        uri="http://example.org/actor/2",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    Triple.objects.create(
        subject=project_resource,
        predicate=workspace_setup["actor_property"],
        object=actor_resource,
        source=organization,
    )

    field_metadata = service.get_field_metadata("Projekt")
    field_metadata, join_field_map = service.augment_field_metadata_with_joins(
        "Projekt",
        field_metadata,
    )

    form = DatasetEntityForm(field_metadata=field_metadata)
    _remove_join_source_fields(form, join_field_map)

    relationships = service.collect_relationship_values(
        dataset_name="Projekt",
        entity_uri=project_resource.uri,
        field_metadata=field_metadata,
        join_field_map=join_field_map,
    )

    direct_relationship = next(
        rel for rel in relationships if not rel.is_join and rel.field_name in form.fields
    )

    read_only = _apply_relationship_initials(
        service=service,
        form=form,
        relationships=[direct_relationship],
        mutate_form=False,
    )
    assert "actor_refs" not in form.initial
    assert read_only == []

    read_only_after_mutation = _apply_relationship_initials(
        service=service,
        form=form,
        relationships=[direct_relationship],
        mutate_form=True,
    )
    assert "actor_refs" in form.initial
    payload = json.loads(form.initial["actor_refs"])
    assert payload[0]["uri"] == actor_resource.uri
    assert read_only_after_mutation == []


@pytest.mark.django_db
def test_list_triple_relationships_provides_labels(workspace_setup):
    service = workspace_setup["service"]
    organization = workspace_setup["organization"]

    actor_resource = Resource.objects.create(
        uri="http://example.org/actor/10",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Akteur 10",
    )
    subject_resource = Resource.objects.create(
        uri="http://example.org/project/10",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Projekt 10",
    )
    actor_property = workspace_setup["actor_property"]

    Triple.objects.create(
        subject=subject_resource,
        predicate=actor_property,
        object=actor_resource,
        source=organization,
    )

    triples = service.list_triple_relationships(
        subject_uri=subject_resource.uri,
        predicate_uri=actor_property.uri,
        target_dataset="Akteurin",
    )
    assert len(triples) == 1
    assert triples[0]["uri"] == actor_resource.uri
    assert triples[0]["label"]


@pytest.mark.django_db
def test_suggest_triple_targets_returns_candidates(workspace_setup):
    service = workspace_setup["service"]
    organization = workspace_setup["organization"]

    dataset_resource = service.get_dataset_schema("Projekt")["dataset_resource"]
    subject_resource = Resource.objects.create(
        uri="http://example.org/project/42",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Projekt 42",
    )
    anchor_property = service.get_dataset_schema("Projekt")["properties"]["projekt_id"]
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        organization=organization,
        value="Projekt 42",
        name="Projekt 42",
    )
    Triple.objects.create(
        subject=subject_resource,
        predicate=anchor_property,
        object=literal,
        source=organization,
    )
    is_part_of = Resource.objects.get(uri="http://purl.org/dc/terms/isPartOf")
    Triple.objects.create(
        subject=subject_resource,
        predicate=is_part_of,
        object=dataset_resource,
        source=organization,
    )

    suggestions = service.suggest_triple_targets(
        target_dataset="Projekt",
        query="42",
    )
    assert suggestions
    assert any(item["uri"] == subject_resource.uri for item in suggestions)
