"""Tests for TripleRelationshipService."""

import pytest

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.catalog.tests.sample_card_data import create_sample_catalog_triples
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


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


def _property(uri: str, canonical: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        resource_type=ResourceType.PROPERTY,
        canonical_uri=canonical,
    )


@pytest.mark.django_db
def test_event_data_resolves_entity_backed_fields():
    org = Organization.objects.create(name="Film University", code="fuk")
    project = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    event = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/ereignis/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    description_entity = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/beschreibung/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    description_literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Aufführungsabend im großen Saal",
    )

    location_entity = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/ort/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    location_literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Folkwang Campus Essen",
    )

    event_type_entity = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/ereignistyp/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    event_type_literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Aufführung",
    )

    start_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="2014-05")
    end_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="2014-05")
    name_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="Passage")

    event_pred = _property("http://example.org/preds/event", ProjectURIs.EVENT)
    start_pred = _property("http://example.org/preds/event-start", ProjectURIs.EVENT_START)
    end_pred = _property("http://example.org/preds/event-end", ProjectURIs.EVENT_END)
    name_pred = _property("http://example.org/preds/event-name", ProjectURIs.EVENT_NAME)
    description_pred = _property("http://example.org/preds/event-description", ProjectURIs.EVENT_DESCRIPTION)
    description_value_pred = _property("http://example.org/preds/beschreibung", "http://arkumu.org/data/properties/beschreibung")
    location_pred = _property("http://example.org/preds/event-location", ProjectURIs.EVENT_LOCATION)
    location_label_pred = _property(
        "http://example.org/preds/location-name",
        "http://arkumu.org/data/properties/deutscher-name-des-ortes",
    )
    event_type_pred = _property("http://example.org/preds/event-type", ProjectURIs.EVENT_TYPE)
    event_type_label_pred = _property(
        "http://example.org/preds/event-type-name",
        "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
    )

    Triple.objects.create(subject=project, predicate=event_pred, object=event, source=org)
    Triple.objects.create(subject=event, predicate=start_pred, object=start_literal, source=org)
    Triple.objects.create(subject=event, predicate=end_pred, object=end_literal, source=org)
    Triple.objects.create(subject=event, predicate=name_pred, object=name_literal, source=org)
    Triple.objects.create(subject=event, predicate=description_pred, object=description_entity, source=org)
    Triple.objects.create(subject=description_entity, predicate=description_value_pred, object=description_literal, source=org)
    Triple.objects.create(subject=event, predicate=location_pred, object=location_entity, source=org)
    Triple.objects.create(subject=location_entity, predicate=location_label_pred, object=location_literal, source=org)
    Triple.objects.create(subject=event, predicate=event_type_pred, object=event_type_entity, source=org)
    Triple.objects.create(subject=event_type_entity, predicate=event_type_label_pred, object=event_type_literal, source=org)

    service = TripleRelationshipService(organization_code="fuk")
    events = service.get_detailed_event_data(
        str(project.id),
        event_predicate=ProjectURIs.EVENT,
        event_start_predicate=ProjectURIs.EVENT_START,
        event_end_predicate=ProjectURIs.EVENT_END,
        event_name_predicate=ProjectURIs.EVENT_NAME,
        event_description_predicate=ProjectURIs.EVENT_DESCRIPTION,
        event_location_predicate=ProjectURIs.EVENT_LOCATION,
        event_location_wikidata_predicate=ProjectURIs.EVENT_LOCATION_WIKIDATA,
        event_type_predicate=ProjectURIs.EVENT_TYPE,
        organization_code="fuk",
    )

    assert len(events) == 1
    event_entry = events[0]
    assert event_entry['name'] == "Passage"
    assert event_entry['description'] == "Aufführungsabend im großen Saal"
    assert event_entry['location'] == "Folkwang Campus Essen"
    assert event_entry['location_id'] == str(location_entity.id)
    assert event_entry['type'] == "Aufführung"


@pytest.mark.django_db
def test_event_data_resolves_wikidata_only_locations():
    org = Organization.objects.create(name="KHM", code="khm")
    project = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    event = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/ereignis/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    start_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="2010-06")
    end_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="2010-06")
    wikidata_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="Q521612")
    location_name_literal = Resource.objects.create(resource_type=ResourceType.LITERAL, value="Köln, Deutschland")

    location_resource = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/ort/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    event_pred = _property("http://example.org/khm/preds/event", ProjectURIs.EVENT)
    start_pred = _property("http://example.org/khm/preds/start", ProjectURIs.EVENT_START)
    end_pred = _property("http://example.org/khm/preds/end", ProjectURIs.EVENT_END)
    wikidata_pred = _property("http://example.org/khm/preds/location-wikidata", ProjectURIs.EVENT_LOCATION_WIKIDATA)
    location_wikidata_link = _property("http://example.org/khm/preds/wikidata", "http://arkumu.org/data/properties/wikidata-id")
    location_label_pred = _property(
        "http://example.org/khm/preds/location-name",
        "http://arkumu.org/data/properties/deutscher-name-des-ortes",
    )

    Triple.objects.create(subject=project, predicate=event_pred, object=event, source=org)
    Triple.objects.create(subject=event, predicate=start_pred, object=start_literal, source=org)
    Triple.objects.create(subject=event, predicate=end_pred, object=end_literal, source=org)
    Triple.objects.create(subject=event, predicate=wikidata_pred, object=wikidata_literal, source=org)
    Triple.objects.create(subject=location_resource, predicate=location_wikidata_link, object=wikidata_literal, source=org)
    Triple.objects.create(subject=location_resource, predicate=location_label_pred, object=location_name_literal, source=org)

    service = TripleRelationshipService(organization_code="khm")
    events = service.get_detailed_event_data(
        str(project.id),
        event_predicate=ProjectURIs.EVENT,
        event_start_predicate=ProjectURIs.EVENT_START,
        event_end_predicate=ProjectURIs.EVENT_END,
        event_name_predicate=ProjectURIs.EVENT_NAME,
        event_description_predicate=ProjectURIs.EVENT_DESCRIPTION,
        event_location_predicate=ProjectURIs.EVENT_LOCATION,
        event_location_wikidata_predicate=ProjectURIs.EVENT_LOCATION_WIKIDATA,
        event_type_predicate=ProjectURIs.EVENT_TYPE,
        organization_code="khm",
    )

    assert len(events) == 1
    event_entry = events[0]
    assert event_entry['location_id'] == 'Q521612'
    assert event_entry['location'] == "Köln, Deutschland"
