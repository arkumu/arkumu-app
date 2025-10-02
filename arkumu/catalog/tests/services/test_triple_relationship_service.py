"""Tests for TripleRelationshipService."""

import pytest

from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.catalog.tests.sample_card_data import create_sample_catalog_triples
from arkumu.metadata.models import Resource, ResourceType, Triple


@pytest.mark.django_db
def test_triple_relationship_service_returns_expected_relationships():
    data = create_sample_catalog_triples()
    project_id = data['project_id']
    schema = data['schema']

    service = TripleRelationshipService()

    project_section = schema.sections['project']
    institution_section = schema.sections['institution']
    category_section = schema.sections['project_category']
    event_section = schema.sections['event']
    actor_event_section = schema.sections['actor_event']
    actor_section = schema.sections['actor']
    role_section = schema.sections['role']
    digital_section = schema.sections['digital_object']

    institution = service.get_institution_data(
        project_id,
        institution_predicate=project_section.properties['institution'].canonical_uri,
        institution_label_predicate=institution_section.properties['german_name'].canonical_uri,
    )
    assert institution == 'Test Institution'

    categories = service.get_category_data(
        project_id,
        category_predicate=project_section.properties['category'].canonical_uri,
        category_label_predicate=category_section.properties['german_name'].canonical_uri,
    )
    assert categories == ['Category']

    event_info = service.get_event_data(
        project_id,
        event_predicate=project_section.properties['event'].canonical_uri,
        event_start_predicate=event_section.properties['start'].canonical_uri,
        event_end_predicate=event_section.properties['end'].canonical_uri,
    )

    assert len(event_info['event_ids']) == 1
    event_id = event_info['event_ids'][0]
    assert event_info['event_details'][event_id]['start'] == '2020-01-01'
    assert event_info['event_details'][event_id]['end'] == '2021-01-01'

    actors = service.get_actor_relationships(
        project_id,
        event_predicate=project_section.properties['event'].canonical_uri,
        actor_link_predicate=actor_event_section.properties['actor_link'].canonical_uri,
        role_link_predicate=actor_event_section.properties['role_link'].canonical_uri,
        actor_name_predicate=actor_section.properties['name'].canonical_uri,
        role_name_predicate=role_section.properties['name'].canonical_uri,
        event_ids=event_info['event_ids'],
    )

    assert len(actors) == 1
    actor_entry = actors[0]
    assert actor_entry['name'] == 'Alice Example'
    assert actor_entry['roles'] == ['Designer']
    assert actor_entry['event_ids'] == [event_id]

    digital_paths = service.get_digital_object_paths(
        project_id,
        link_predicate='http://arkumu.org/data/properties/digitales-objekt',
        path_predicate=digital_section.properties['path'].canonical_uri,
    )
    assert digital_paths == ['path/to/file.jpg']


@pytest.mark.django_db
def test_get_actor_relationships_direct_edges_fallback():
    project = Resource.objects.create(
        uri="http://example.org/project/dir-1",
        resource_type=ResourceType.ENTITY,
    )
    actor = Resource.objects.create(
        uri="http://example.org/actor/1",
        resource_type=ResourceType.ENTITY,
    )

    actor_link_predicate = Resource.objects.create(
        uri="http://example.org/preds/actor-link",
        resource_type=ResourceType.PROPERTY,
        canonical_uri="http://arkumu.org/data/properties/akteurin-im-ereignis",
    )
    actor_name_predicate = Resource.objects.create(
        uri="http://example.org/preds/actor-name",
        resource_type=ResourceType.PROPERTY,
        canonical_uri="http://arkumu.org/data/properties/deutscher-name",
    )

    actor_name_literal = Resource.objects.create(
        value="Fallback Actor",
        resource_type=ResourceType.LITERAL,
    )

    Triple.objects.create(
        subject=project,
        predicate=actor_link_predicate,
        object=actor,
    )

    Triple.objects.create(
        subject=actor,
        predicate=actor_name_predicate,
        object=actor_name_literal,
    )

    service = TripleRelationshipService()
    actors = service.get_actor_relationships(
        str(project.id),
        event_predicate=None,
        actor_link_predicate="http://arkumu.org/data/properties/akteurin-im-ereignis",
        role_link_predicate=None,
        actor_name_predicate="http://arkumu.org/data/properties/deutscher-name",
        role_name_predicate=None,
    )

    assert actors == [
        {
            'id': str(actor.id),
            'name': 'Fallback Actor',
            'roles': [],
            'event_ids': [],
        }
    ]


@pytest.mark.django_db
def test_get_actor_relationships_event_edge_fallback():
    project = Resource.objects.create(
        uri="http://example.org/project/event-1",
        resource_type=ResourceType.ENTITY,
    )
    event = Resource.objects.create(
        uri="http://example.org/event/1",
        resource_type=ResourceType.ENTITY,
    )
    actor = Resource.objects.create(
        uri="http://example.org/actor/evt",
        resource_type=ResourceType.ENTITY,
    )

    event_predicate = Resource.objects.create(
        uri="http://example.org/preds/event",
        resource_type=ResourceType.PROPERTY,
        canonical_uri="http://arkumu.org/data/properties/ereignis",
    )
    actor_link_predicate = Resource.objects.create(
        uri="http://example.org/preds/actor-link",
        resource_type=ResourceType.PROPERTY,
        canonical_uri="http://arkumu.org/data/properties/akteurin-im-ereignis",
    )
    actor_name_predicate = Resource.objects.create(
        uri="http://example.org/preds/actor-name",
        resource_type=ResourceType.PROPERTY,
        canonical_uri="http://arkumu.org/data/properties/deutscher-name",
    )

    actor_name_literal = Resource.objects.create(
        value="Event Actor",
        resource_type=ResourceType.LITERAL,
    )

    Triple.objects.create(
        subject=project,
        predicate=event_predicate,
        object=event,
    )
    Triple.objects.create(
        subject=event,
        predicate=actor_link_predicate,
        object=actor,
    )
    Triple.objects.create(
        subject=actor,
        predicate=actor_name_predicate,
        object=actor_name_literal,
    )

    service = TripleRelationshipService()
    actors = service.get_actor_relationships(
        str(project.id),
        event_predicate="http://arkumu.org/data/properties/ereignis",
        actor_link_predicate="http://arkumu.org/data/properties/akteurin-im-ereignis",
        role_link_predicate=None,
        actor_name_predicate="http://arkumu.org/data/properties/deutscher-name",
        role_name_predicate=None,
    )

    assert actors == [
        {
            'id': str(actor.id),
            'name': 'Event Actor',
            'roles': [],
            'event_ids': [str(event.id)],
        }
    ]
