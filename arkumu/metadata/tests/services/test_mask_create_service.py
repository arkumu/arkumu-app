import pytest

from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.mask_create_service import MaskCreateService
from arkumu.users.models import Organization


@pytest.fixture
@pytest.mark.django_db
def organization():
    return Organization.objects.create(name="Folkwang", code="fuk")


def _create_typed_option(*, organization, type_uri, resource_uri, label, label_predicate_uri):
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={
            "canonical_uri": type_uri,
            "resource_type": ResourceType.CLASS,
        },
    )
    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={
            "canonical_uri": RDF_TYPE_URI,
            "resource_type": ResourceType.PROPERTY,
        },
    )
    label_predicate, _ = Resource.objects.get_or_create(
        uri=label_predicate_uri,
        defaults={
            "canonical_uri": label_predicate_uri,
            "resource_type": ResourceType.PROPERTY,
        },
    )

    resource = Resource.objects.create(
        uri=resource_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name=label,
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value=label,
        organization=organization,
    )

    Triple.objects.create(subject=resource, predicate=rdf_type_resource, object=type_resource, source=organization)
    Triple.objects.create(subject=resource, predicate=label_predicate, object=literal, source=organization)
    return resource


@pytest.mark.django_db
def test_mask_create_service_exposes_project_create_fields_with_vocabulary_options(organization):
    _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/einliefernde-hochschule",
        resource_uri="http://arkumu.org/data/fuk/entities/institution/1",
        label="Folkwang Universität",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    )
    _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/projektart",
        resource_uri="http://arkumu.org/data/fuk/entities/project-type/1",
        label="Konzert",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektart",
    )

    service = MaskCreateService(organization.code, "project")
    manifest = service.get_form_manifest()

    assert manifest.entity_type == "project"
    assert manifest.phase == "create"
    field_names = [field.name for field in manifest.fields]
    assert field_names == ["title", "institution__label", "project_type"]

    institution_field = next(field for field in manifest.fields if field.name == "institution__label")
    assert institution_field.widget == "select"
    assert institution_field.options == [
        ("http://arkumu.org/data/fuk/entities/institution/1", "Folkwang Universität"),
    ]


@pytest.mark.django_db
def test_mask_create_service_persists_project_with_vocab_relations(organization):
    institution = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/einliefernde-hochschule",
        resource_uri="http://arkumu.org/data/fuk/entities/institution/1",
        label="Folkwang Universität",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    )
    project_type = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/projektart",
        resource_uri="http://arkumu.org/data/fuk/entities/project-type/1",
        label="Konzert",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektart",
    )

    service = MaskCreateService(organization.code, "project")
    result = service.persist(
        {
            "title": "Neues Projekt",
            "institution__label": institution.uri,
            "project_type": project_type.uri,
        }
    )

    assert result.success is True
    assert result.resource is not None
    assert result.resource.name == "Neues Projekt"

    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri=CardURIs.INSTITUTION,
        object=institution,
    ).exists()
    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri=ProjectURIs.PROJECT_TYPE_FIELD,
        object=project_type,
    ).exists()


@pytest.mark.django_db
def test_mask_create_service_persists_event_and_requires_event_type(organization):
    event_type = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/ereignistyp",
        resource_uri="http://arkumu.org/data/fuk/entities/event-type/1",
        label="Aufführung",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
    )

    service = MaskCreateService(organization.code, "event")

    invalid = service.persist({})
    assert invalid.success is False
    assert invalid.field_errors == {"event_type": "Pflichtfeld"}

    result = service.persist({"event_type": event_type.uri})
    assert result.success is True
    assert result.resource is not None

    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri=RDF_TYPE_URI,
        object__uri=CardURIs.EVENT_TYPE,
    ).exists()
    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri=ProjectURIs.EVENT_TYPE,
        object=event_type,
    ).exists()


@pytest.mark.django_db
def test_mask_create_service_persists_actor_and_requires_one_name(organization):
    service = MaskCreateService(organization.code, "actor")

    invalid = service.persist({})
    assert invalid.success is False
    assert invalid.field_errors == {
        "name_de": "Mindestens einer der beiden Namen ist erforderlich.",
        "name_en": "Mindestens einer der beiden Namen ist erforderlich.",
    }

    result = service.persist({"name_en": "John Doe"})
    assert result.success is True
    assert result.resource is not None
    assert result.resource.name == "John Doe"

    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri=RDF_TYPE_URI,
        object__uri=CardURIs.ACTOR_TYPE,
    ).exists()
    assert Triple.objects.filter(
        subject=result.resource,
        predicate__uri="http://arkumu.org/data/properties/englischer-name",
        object__value="John Doe",
    ).exists()
