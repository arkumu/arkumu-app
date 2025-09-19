"""Targeted tests for multi-value FK literal handling and junction expansion."""

from typing import Dict, List, Optional

import pytest

from arkumu.users.models import Organization
from arkumu.metadata.models import Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import (
    MappingAwareProcessor,
    ProcessingContext,
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer import (
    ColumnConfig,
    ColumnType,
    DatasetConfig,
    ExecutionConfig,
    FKRelationship,
    RelationshipContext,
)


def _make_column(dataset_name: str,
                 column_name: str,
                 arkumu_type: str,
                 column_type: ColumnType = ColumnType.REGULAR,
                 **overrides) -> ColumnConfig:
    """Create a ColumnConfig with convenient overrides for tests."""

    column = ColumnConfig(
        column_name=column_name,
        dataset_name=dataset_name,
        arkumu_type=arkumu_type,
    )
    column.column_type = column_type

    for attr, value in overrides.items():
        setattr(column, attr, value)

    return column


def _build_execution_config(org_code: str,
                            datasets: List[DatasetConfig],
                            columns: List[ColumnConfig],
                            fk_relationships: List[FKRelationship],
                            relationship_contexts: Optional[List[RelationshipContext]] = None) -> ExecutionConfig:
    """Assemble an ExecutionConfig for the processor tests."""

    column_lookup = {
        f"{column.dataset_name}.{column.column_name}": column
        for column in columns
    }

    return ExecutionConfig(
        mapping_id=1,
        mapping_name="Test Import",
        organization=org_code,
        datasets=datasets,
        column_configurations=column_lookup,
        fk_relationships=fk_relationships,
        relationship_contexts=relationship_contexts or [],
    )


def _make_context(execution_config: ExecutionConfig,
                  csv_sources: Dict[str, List[Dict[str, str]]]) -> ProcessingContext:
    """Create a fresh processing context for direct method invocation."""

    return ProcessingContext(
        execution_config=execution_config,
        current_dataset="",
        all_csv_sources=csv_sources,
        entity_cache={},
        processed_datasets=set(),
    )


@pytest.mark.django_db
def test_multi_value_fk_columns_create_literal_triples():
    """Multi-value FK columns should still emit literal triples for each split value."""

    org = Organization.objects.create(code="MVFK", name="Multi Value FK Org")
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(
        organization=org,
        base_uri=f"http://arkumu.org/data/{org.code}",
        statistics=statistics,
    )

    # Column definitions
    person_id = _make_column(
        "Person",
        "ID",
        "person_id",
        column_type=ColumnType.ANCHOR,
        is_anchor=True,
    )
    event_id = _make_column(
        "Event",
        "ID",
        "event_id",
        column_type=ColumnType.ANCHOR,
        is_anchor=True,
    )
    participants = _make_column(
        "Event",
        "Participants",
        "participants",
        column_type=ColumnType.MULTI_VALUE_FOREIGN_KEY,
        is_multi_value=True,
        multi_value_separator=",",
        is_fk=True,
        fk_config={
            "target_dataset": "Person",
            "target_column": "ID",
            "relationship_type": "hasParticipant",
        },
    )

    participant_fk = FKRelationship(
        source_column="Participants",
        source_dataset="Event",
        target_column="ID",
        target_dataset="Person",
        relationship_type="hasParticipant",
        is_multi_value=True,
        multi_value_separator=",")

    person_dataset = DatasetConfig(dataset_name="Person", columns=[person_id])
    event_dataset = DatasetConfig(dataset_name="Event", columns=[event_id, participants])
    event_dataset.fk_relationships = [participant_fk]

    execution_config = _build_execution_config(
        org.code,
        datasets=[person_dataset, event_dataset],
        columns=[person_id, event_id, participants],
        fk_relationships=[participant_fk],
    )

    csv_sources = {
        "Person": [
            {"ID": "P001"},
            {"ID": "P002"},
            {"ID": "P003"},
        ],
        "Event": [
            {"ID": "E001", "Participants": "P001,P002,P003"},
        ],
    }

    context = _make_context(execution_config, csv_sources)

    context.current_dataset = "Person"
    processor._process_dataset_with_entities(person_dataset, csv_sources["Person"], context)

    context.current_dataset = "Event"
    processor._process_dataset_with_entities(event_dataset, csv_sources["Event"], context)

    property_uri = processor._generate_property_uri("participants")
    triples = Triple.objects.filter(predicate__uri=property_uri)

    assert triples.count() == 3
    assert {triple.object.value for triple in triples} == {"P001", "P002", "P003"}


@pytest.mark.django_db
def test_junction_entities_expand_multi_value_fk_combinations():
    """Junction processing should create one entity per FK combination."""

    org = Organization.objects.create(code="JCTX", name="Junction Context Org")
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(
        organization=org,
        base_uri=f"http://arkumu.org/data/{org.code}",
        statistics=statistics,
    )

    # Base columns
    actor_id = _make_column(
        "Actor",
        "ID",
        "actor_id",
        column_type=ColumnType.ANCHOR,
        is_anchor=True,
    )
    event_id = _make_column(
        "Event",
        "ID",
        "event_id",
        column_type=ColumnType.ANCHOR,
        is_anchor=True,
    )

    junction_actor_id = _make_column(
        "ActorEvent",
        "ActorID",
        "actor_fk",
        column_type=ColumnType.MULTI_VALUE_FOREIGN_KEY,
        is_fk=True,
        is_multi_value=True,
        multi_value_separator=",",
        fk_config={
            "target_dataset": "Actor",
            "target_column": "ID",
            "relationship_type": "participatesIn",
        },
    )
    junction_event_ids = _make_column(
        "ActorEvent",
        "EventIDs",
        "event_fk",
        column_type=ColumnType.MULTI_VALUE_FOREIGN_KEY,
        is_fk=True,
        is_multi_value=True,
        multi_value_separator=",",
        fk_config={
            "target_dataset": "Event",
            "target_column": "ID",
            "relationship_type": "participatesIn",
        },
    )
    junction_role = _make_column(
        "ActorEvent",
        "Role",
        "role",
        column_type=ColumnType.RELATIONSHIP_CONTEXT,
    )

    actor_fk = FKRelationship(
        source_column="ActorID",
        source_dataset="ActorEvent",
        target_column="ID",
        target_dataset="Actor",
        relationship_type="participatesIn",
        is_multi_value=True,
        multi_value_separator=",")
    event_fk = FKRelationship(
        source_column="EventIDs",
        source_dataset="ActorEvent",
        target_column="ID",
        target_dataset="Event",
        relationship_type="participatesIn",
        is_multi_value=True,
        multi_value_separator=",")

    actor_dataset = DatasetConfig(dataset_name="Actor", columns=[actor_id])
    event_dataset = DatasetConfig(dataset_name="Event", columns=[event_id])
    junction_dataset = DatasetConfig(
        dataset_name="ActorEvent",
        columns=[junction_actor_id, junction_event_ids, junction_role],
    )
    junction_dataset.fk_relationships = [actor_fk, event_fk]

    relationship_context = RelationshipContext(
        context_id="actor_event_role",
        primary_fk="ActorID",
        secondary_fk="EventIDs",
        context_columns=["Role"],
        context_type="attribute",
        dataset_name="ActorEvent",
    )
    relationship_context.primary_entity_type = "Actor"
    relationship_context.secondary_entity_type = "Event"
    relationship_context.junction_attributes = ["Role"]

    execution_config = _build_execution_config(
        org.code,
        datasets=[actor_dataset, event_dataset, junction_dataset],
        columns=[
            actor_id,
            event_id,
            junction_actor_id,
            junction_event_ids,
            junction_role,
        ],
        fk_relationships=[actor_fk, event_fk],
        relationship_contexts=[relationship_context],
    )

    csv_sources = {
        "Actor": [
            {"ID": "A1"},
            {"ID": "A2"},
            {"ID": "A3"},
        ],
        "Event": [
            {"ID": "E1"},
            {"ID": "E2"},
            {"ID": "E3"},
        ],
        "ActorEvent": [
            {"ActorID": "A1", "EventIDs": "E1,E2,E3", "Role": "Speaker"},
            {"ActorID": "A2,A3", "EventIDs": "E2,E3", "Role": "Attendee"},
        ],
    }

    context = _make_context(execution_config, csv_sources)

    context.current_dataset = "Actor"
    processor._process_dataset_with_entities(actor_dataset, csv_sources["Actor"], context)

    context.current_dataset = "Event"
    processor._process_dataset_with_entities(event_dataset, csv_sources["Event"], context)

    context.current_dataset = "ActorEvent"
    processor._process_dataset_with_entities(junction_dataset, csv_sources["ActorEvent"], context)

    # Process the relationship context to build junction entities
    processor._process_all_relationship_contexts(context)

    expected_pairs = {
        ("A1", "E1"),
        ("A1", "E2"),
        ("A1", "E3"),
        ("A2", "E2"),
        ("A2", "E3"),
        ("A3", "E2"),
        ("A3", "E3"),
    }

    expected_uris = {
        processor.resource_manager.generate_junction_uri("ActorEvent", actor, event)
        for actor, event in expected_pairs
    }

    junction_resources = Resource.objects.filter(
        uri__in=expected_uris,
        organization=org,
    )

    assert junction_resources.count() == len(expected_uris)

    for actor_value, event_value in expected_pairs:
        junction_uri = processor.resource_manager.generate_junction_uri(
            "ActorEvent",
            actor_value,
            event_value,
        )
        junction_resource = Resource.objects.get(uri=junction_uri)

        actor_uri = processor.resource_manager.generate_entity_uri("Actor", actor_value)
        event_uri = processor.resource_manager.generate_entity_uri("Event", event_value)

        involves_primary = processor._generate_property_uri("involves_primary")
        involves_secondary = processor._generate_property_uri("involves_secondary")

        assert Triple.objects.filter(
            subject=junction_resource,
            predicate__uri=involves_primary,
            object__uri=actor_uri,
        ).exists()

        assert Triple.objects.filter(
            subject=junction_resource,
            predicate__uri=involves_secondary,
            object__uri=event_uri,
        ).exists()

    role_property_uri = processor._generate_property_uri("junction_role")
    role_triples = Triple.objects.filter(predicate__uri=role_property_uri)
    assert role_triples.count() == len(expected_pairs)
    assert {
        triple.object.value for triple in role_triples
    } == {"Speaker", "Attendee"}

    combined_uri = processor.resource_manager.generate_junction_uri(
        "ActorEvent",
        "A2,A3",
        "E2,E3",
    )
    assert not Resource.objects.filter(uri=combined_uri).exists()
