import pytest

from arkumu.metadata.entity_creation.forms import ProjectForm
from arkumu.metadata.entity_creation import EntityCreationService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.users.models import Organization


@pytest.fixture(autouse=True)
def rdf_type_resource(db):
    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
        },
    )


def _project_metadata_options():
    return {
        "project": [],
        "institution": [("http://example.org/institution/1", "Institution 1")],
        "project_category": [("http://example.org/category/1", "Category 1")],
        "description": [("http://example.org/description/1", "Description 1")],
        "catchphrase": [("http://example.org/catchphrase/1", "Catchphrase 1")],
        "project_type": [("http://example.org/type/1", "Type 1")],
        "digital_object": [("http://example.org/object/1", "Object 1")],
    }


@pytest.mark.django_db
def test_entity_creation_service_creates_project_and_initial_data():
    organization = Organization.objects.create(code="testorg", name="Test Org")
    metadata_options = _project_metadata_options()

    form = ProjectForm(
        data={
            "uri": "",
            "bevorzugter_titel": "Test Project",
            "bevorzugter_untertitel": "Subtitle",
            "einliefernde_hochschule_uri": "http://example.org/institution/1",
            "projektkategorie_uri": "http://example.org/category/1",
            "beschreibung": "Project description",
            "schlagwort_uris": ["http://example.org/catchphrase/1"],
            "projektart_uri": "http://example.org/type/1",
            "vorschaubild_uri": "http://example.org/object/1",
        },
        metadata_options=metadata_options,
    )
    assert form.is_valid()

    service = EntityCreationService.for_key("project", organization)
    entity, created = service.create_or_update_from_form(form)

    assert created is True
    assert f"/{organization.code}/" in entity._resource.uri

    initial_data = service.build_initial_data(entity)
    assert initial_data["bevorzugter_titel"] == "Test Project"
    assert initial_data["bevorzugter_untertitel"] == "Subtitle"
    assert initial_data["einliefernde_hochschule_uri"] == "http://example.org/institution/1"
    assert initial_data["projektkategorie_uri"] == "http://example.org/category/1"
    assert initial_data["beschreibung"] == "Project description"
    assert initial_data["projektart_uri"] == "http://example.org/type/1"
    assert initial_data["schlagwort_uris"] == ["http://example.org/catchphrase/1"]
    assert initial_data["vorschaubild_uri"] == "http://example.org/object/1"


@pytest.mark.django_db
def test_initial_data_builder_handles_missing_uri():
    organization = Organization.objects.create(code="initorg", name="Init Org")
    service = EntityCreationService.for_key("project", organization)

    from arkumu.metadata.entity_creation.services import EntityInitialDataBuilder

    initial_builder = EntityInitialDataBuilder(service)
    assert initial_builder.get_initial_for_uri("http://example.org/missing") is None
