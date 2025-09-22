"""Utilities for creating catalog card test data."""

from __future__ import annotations

import copy
from typing import Dict, List

from arkumu.catalog.services.schema_manifest_service import CARD_SCHEMA_TEMPLATE, CardSchema
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple


def build_schema_with_relationships() -> CardSchema:
    """Create a card schema with FK metadata for tests."""

    schema = copy.deepcopy(CARD_SCHEMA_TEMPLATE)

    project_section = schema.sections['project']
    institution_section = schema.sections['institution']
    category_section = schema.sections['project_category']
    event_section = schema.sections['event']
    actor_event_section = schema.sections['actor_event']
    actor_section = schema.sections['actor']
    role_section = schema.sections['role']
    digital_object_section = schema.sections['digital_object']

    project_section.fk_relationships = [
        {
            'source_property': project_section.properties['institution'].canonical_uri,
            'target_property': institution_section.properties['german_name'].canonical_uri,
        },
        {
            'source_property': project_section.properties['category'].canonical_uri,
            'target_property': category_section.properties['german_name'].canonical_uri,
        },
        {
            'source_property': project_section.properties['event'].canonical_uri,
            'target_property': event_section.properties['start'].canonical_uri,
        },
        {
            'source_property': project_section.properties['event'].canonical_uri,
            'target_property': event_section.properties['end'].canonical_uri,
        },
        {
            'source_property': 'http://arkumu.org/data/properties/digitales-objekt',
            'target_property': digital_object_section.properties['path'].canonical_uri,
        },
    ]

    event_section.fk_relationships = [
        {
            'source_property': actor_event_section.properties['actor_link'].canonical_uri,
            'target_property': actor_event_section.properties['actor_link'].canonical_uri,
        },
        {
            'source_property': actor_event_section.properties['role_link'].canonical_uri,
            'target_property': actor_event_section.properties['role_link'].canonical_uri,
        },
    ]

    actor_event_section.fk_relationships = [
        {
            'source_property': actor_event_section.properties['actor_link'].canonical_uri,
            'target_property': actor_section.properties['name'].canonical_uri,
        },
        {
            'source_property': actor_event_section.properties['role_link'].canonical_uri,
            'target_property': role_section.properties['name'].canonical_uri,
        },
    ]

    return schema


def create_sample_catalog_triples() -> Dict[str, object]:
    """Create resources and triples representing a catalog card."""

    schema = build_schema_with_relationships()

    predicates = {
        'title': 'http://arkumu.org/data/properties/bevorzugter-titel',
        'event': 'http://arkumu.org/data/properties/ereignis',
        'institution': 'http://arkumu.org/data/properties/einliefernde-hochschule',
        'category': 'http://arkumu.org/data/properties/projektkategorie',
        'digital_link': 'http://arkumu.org/data/properties/digitales-objekt',
        'event_start': 'http://arkumu.org/data/properties/ereignisbeginn',
        'event_end': 'http://arkumu.org/data/properties/ereignisende',
        'actor_link': 'http://arkumu.org/data/properties/akteurin-im-ereignis',
        'role_link': 'http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis',
        'actor_name': 'http://arkumu.org/data/properties/deutscher-name',
        'role_name': 'http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb',
        'institution_name': 'http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule',
        'category_name': 'http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb',
        'digital_path': 'http://arkumu.org/data/properties/dateipfad',
    }

    predicate_resources: Dict[str, Resource] = {}
    for key, uri in predicates.items():
        predicate_resources[key] = Resource.objects.create(
            uri=uri,
            canonical_uri=uri,
            resource_type=ResourceType.PROPERTY,
            name=key,
        )

    project = Resource.objects.create(
        uri='http://example.org/project/1',
        resource_type=ResourceType.ENTITY,
        name='Sample Project',
    )

    event = Resource.objects.create(
        uri='http://example.org/event/1',
        resource_type=ResourceType.ENTITY,
        name='Sample Event',
    )

    institution = Resource.objects.create(
        uri='http://example.org/institution/1',
        resource_type=ResourceType.ENTITY,
        name='Sample Institution',
    )

    category = Resource.objects.create(
        uri='http://example.org/category/1',
        resource_type=ResourceType.ENTITY,
        name='Sample Category',
    )

    digital_object = Resource.objects.create(
        uri='http://example.org/digital/1',
        resource_type=ResourceType.ENTITY,
        name='Digital Object',
    )

    crosstable = Resource.objects.create(
        uri='http://example.org/crosstable/1',
        resource_type=ResourceType.ENTITY,
        name='Event Actor Crosstable',
    )

    actor = Resource.objects.create(
        uri='http://example.org/actor/1',
        resource_type=ResourceType.ENTITY,
        name='Actor Resource',
    )

    role = Resource.objects.create(
        uri='http://example.org/role/1',
        resource_type=ResourceType.ENTITY,
        name='Role Resource',
    )

    def literal(value: str) -> Resource:
        return Resource.objects.create(
            value=value,
            resource_type=ResourceType.LITERAL,
        )

    triples: List[Triple] = []

    def add(subject: Resource, predicate_key: str, obj_resource: Resource) -> None:
        triples.append(
            Triple.objects.create(
                subject=subject,
                predicate=predicate_resources[predicate_key],
                object=obj_resource,
            )
        )

    add(project, 'title', literal('Project Title'))
    add(project, 'event', event)
    add(project, 'institution', institution)
    add(project, 'category', category)
    add(project, 'digital_link', digital_object)

    add(event, 'event_start', literal('2020-01-01'))
    add(event, 'event_end', literal('2021-01-01'))
    add(event, 'actor_link', crosstable)
    add(event, 'role_link', crosstable)

    add(crosstable, 'actor_link', actor)
    add(crosstable, 'role_link', role)

    add(actor, 'actor_name', literal('Alice Example'))
    add(role, 'role_name', literal('Parent > Designer'))
    add(institution, 'institution_name', literal('Test Institution'))
    add(category, 'category_name', literal('Parent > Category'))
    add(digital_object, 'digital_path', literal('path/to/file.jpg'))

    edges: List[Dict[str, object]] = []
    edges_by_subject: Dict[str, List[Dict[str, object]]] = {}

    for triple in Triple.objects.order_by('id').select_related('predicate', 'object'):
        edge: Dict[str, object] = {
            'subject_id': str(triple.subject_id),
            'predicate_canonical': triple.predicate.canonical_uri,
            'predicate_uri': triple.predicate.uri,
            'object_type': triple.object.resource_type,
        }
        if triple.object.resource_type == ResourceType.LITERAL:
            edge['object_value'] = triple.object.value
        else:
            edge['object_id'] = str(triple.object_id)
        edges.append(edge)
        edges_by_subject.setdefault(str(triple.subject_id), []).append(edge)

    return {
        'schema': schema,
        'project_id': str(project.id),
        'edges': edges,
        'edges_by_subject': edges_by_subject,
        'event_id': str(event.id),
    }
