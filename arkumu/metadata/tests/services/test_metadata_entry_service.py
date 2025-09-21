import pytest

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.metadata_entry_service import MetadataEntryService
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.users.models import Organization


@pytest.fixture
@pytest.mark.django_db
def organization():
    return Organization.objects.create(name="Folkwang", code="fuk")


@pytest.fixture
@pytest.mark.django_db
def service(organization):
    return MetadataEntryService(organization.code)


@pytest.mark.django_db
def test_list_sections(service):
    sections = service.list_sections()
    assert sections
    names = {section["name"] for section in sections}
    assert {"overview", "institution", "classification"}.issubset(names)


@pytest.mark.django_db
def test_get_section_manifest(service):
    manifest = service.get_section_manifest("overview")
    field_names = [field.name for field in manifest.fields]
    assert "title" in field_names
    assert any(field.required for field in manifest.fields)


@pytest.mark.django_db
def test_persist_entry_creates_project(service, organization):
    result = service.persist_entry(
        "overview",
        {
            "title": "Neues Projekt",
            "subtitle": "Ein Abend",
        },
    )

    assert result.success is True
    assert result.resource is not None

    project = result.resource
    assert project.organization == organization
    assert project.resource_type == ResourceType.ENTITY

    title_triple = Triple.objects.filter(
        subject=project,
        predicate__uri=CardURIs.TITLE,
        object__value="Neues Projekt",
    ).exists()
    assert title_triple is True

    type_triple = Triple.objects.filter(
        subject=project,
        predicate__uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        object__uri=CardURIs.PROJECT_TYPE,
    ).exists()
    assert type_triple is True


@pytest.mark.django_db
def test_persist_entry_with_institution(service):
    payload = {
        "title": "Festival",
        "institution__label": "HfMT Köln",
        "project_type": "Konzert",
    }
    result = service.persist_entry("institution", payload)
    assert result.success is True
    project = result.resource
    assert project is not None

    institution_triple = Triple.objects.filter(
        subject=project,
        predicate__uri=CardURIs.INSTITUTION,
        object__name="HfMT Köln",
    ).exists()
    assert institution_triple is True


@pytest.mark.django_db
def test_persist_entry_with_categories_and_catchphrases(service):
    payload = {
        "categories": "Jazz\nPerformance",
        "catchphrases": "Sommer, Live",
    }
    result = service.persist_entry("classification", payload)
    assert result.success is True
    project = result.resource
    assert project is not None

    category_triples = Triple.objects.filter(
        subject=project,
        predicate__uri=CardURIs.CATEGORY,
    )
    assert category_triples.count() == 2

    catchphrase_triples = Triple.objects.filter(
        subject=project,
        predicate__uri=ProjectURIs.CATCHPHRASE,
    )
    assert catchphrase_triples.count() == 2


@pytest.mark.django_db
def test_required_fields_enforced(service):
    result = service.persist_entry("overview", {"subtitle": "Fehlt"})
    assert result.success is False
    assert "title" in result.field_errors
