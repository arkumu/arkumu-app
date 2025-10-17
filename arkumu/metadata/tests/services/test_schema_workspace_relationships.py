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
        "properties": {},
        "column_metadata": {},
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

    badges = _apply_relationship_initials(
        service=service,
        form=form,
        relationships=[direct_relationship],
        mutate_form=False,
    )
    assert "actor_refs" not in form.initial
    assert badges and badges[0]["label"]

    _apply_relationship_initials(
        service=service,
        form=form,
        relationships=[direct_relationship],
        mutate_form=True,
    )
    assert "actor_refs" in form.initial
    payload = json.loads(form.initial["actor_refs"])
    assert payload[0]["uri"] == actor_resource.uri
