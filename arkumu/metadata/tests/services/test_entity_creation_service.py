import pytest

from arkumu.common.uri_utils import mint_uri, slugify_uri_part
from arkumu.metadata.entity_creation.forms import ProjectForm
from arkumu.metadata.entity_creation import EntityCreationService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.schema_workspace.services import DatasetSummary
from arkumu.metadata.models.triples import Triple
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


@pytest.mark.django_db
def test_entity_creation_links_entity_to_dataset():
    organization = Organization.objects.create(code="countorg", name="Count Org")
    metadata_options = _project_metadata_options()

    form = ProjectForm(
        data={
            "uri": "",
            "bevorzugter_titel": "Counting Project",
            "bevorzugter_untertitel": "",
            "einliefernde_hochschule_uri": "http://example.org/institution/1",
            "projektkategorie_uri": "http://example.org/category/1",
            "beschreibung": "",
            "schlagwort_uris": [],
            "projektart_uri": "http://example.org/type/1",
            "vorschaubild_uri": "",
        },
        metadata_options=metadata_options,
    )
    assert form.is_valid()

    service = EntityCreationService.for_key("project", organization)
    entity, created = service.create_or_update_from_form(form)

    assert created is True
    dataset_name = service.dataset_resource_name
    dataset_uri = mint_uri(
        "http://arkumu.org/data",
        organization.code,
        "datasets",
        slugify_uri_part(dataset_name),
    )
    triples = Triple.objects.filter(
        subject=entity._resource,
        predicate__uri="http://purl.org/dc/terms/isPartOf",
        source=organization,
    )
    assert triples.count() == 1
    assert triples.first().object.uri == dataset_uri


@pytest.mark.django_db
def test_existing_entity_selection_backfills_dataset_membership():
    organization = Organization.objects.create(code="linkorg", name="Link Org")
    existing_resource = Resource.objects.create(
        uri="http://arkumu.org/data/linkorg/entities/projekt/existing",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Existing Project",
    )

    metadata_options = _project_metadata_options()
    metadata_options["project"] = [
        (existing_resource.uri, "Existing Project"),
    ]

    form = ProjectForm(
        data={"uri": existing_resource.uri},
        metadata_options=metadata_options,
        disable_fields=True,
    )
    assert form.is_valid()

    service = EntityCreationService.for_key("project", organization)
    entity, created = service.create_or_update_from_form(form)

    assert created is False
    dataset_name = service.dataset_resource_name
    dataset_uri = mint_uri(
        "http://arkumu.org/data",
        organization.code,
        "datasets",
        slugify_uri_part(dataset_name),
    )
    assert Triple.objects.filter(
        subject=entity._resource,
        predicate__uri="http://purl.org/dc/terms/isPartOf",
        object__uri=dataset_uri,
        source=organization,
    ).exists()


@pytest.mark.django_db
def test_dataset_resource_name_inferred_from_mapping(monkeypatch):
    organization = Organization.objects.create(code="maporg", name="Mapping Org")
    Mapping.objects.create(name="MapOrg Mapping", organization_id=organization.code)

    class StubWorkspaceService:
        def __init__(self, *, mapping, organization, base_uri):
            self.mapping = mapping
            self.organization = organization
            self.base_uri = base_uri

        def list_datasets(self):
            return [
                DatasetSummary(
                    dataset_name="00_hfm_projekte",
                    display_label="Projekt",
                    anchor_columns=[],
                    property_count=0,
                    relationship_count=0,
                )
            ]

    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaWorkspaceService",
        StubWorkspaceService,
    )

    service = EntityCreationService.for_key("project", organization)
    assert service.dataset_resource_name == "00_hfm_projekte"
