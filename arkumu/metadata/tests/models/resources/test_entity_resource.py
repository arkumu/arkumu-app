import pytest

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.resources.entity import EntityResource
from arkumu.metadata.models.resources.property import PropertyResource
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


@pytest.fixture
@pytest.mark.django_db
def organization():
    return Organization.objects.create(name="Folkwang", code="fuk")


@pytest.mark.django_db
def test_entity_resource_get_property_falls_back_to_canonical_uri_for_literals(organization):
    canonical_uri = "http://arkumu.org/data/properties/bevorzugter-titel"
    subject = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/projects/test-projekt",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Testprojekt",
    )
    canonical_predicate = Resource.objects.create(
        uri=canonical_uri,
        canonical_uri=canonical_uri,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Bevorzugter Titel",
    )
    mapped_predicate = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/properties/titel",
        canonical_uri=canonical_uri,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Titel",
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Mask Created Title",
        organization=organization,
    )
    Triple.objects.create(
        subject=subject,
        predicate=canonical_predicate,
        object=literal,
        source=organization,
    )

    entity = EntityResource(subject)
    property_resource = PropertyResource(mapped_predicate)

    assert entity.get_property(property_resource) == ["Mask Created Title"]


@pytest.mark.django_db
def test_entity_resource_get_property_falls_back_to_canonical_uri_for_relations(organization):
    canonical_uri = "http://arkumu.org/data/properties/ereignistyp"
    subject = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/events/test-ereignis",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Testereignis",
    )
    target = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/event-type/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Aufführung",
    )
    canonical_predicate = Resource.objects.create(
        uri=canonical_uri,
        canonical_uri=canonical_uri,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Ereignistyp",
    )
    mapped_predicate = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/properties/ereignistyp",
        canonical_uri=canonical_uri,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
        name="Ereignistyp lokal",
    )
    Triple.objects.create(
        subject=subject,
        predicate=canonical_predicate,
        object=target,
        source=organization,
    )

    entity = EntityResource(subject)
    property_resource = PropertyResource(mapped_predicate)
    values = entity.get_property(property_resource)

    assert len(values) == 1
    assert isinstance(values[0], EntityResource)
    assert values[0].uri == target.uri
