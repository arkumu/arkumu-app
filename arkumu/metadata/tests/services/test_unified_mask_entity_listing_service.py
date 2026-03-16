import pytest

from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.unified_mask_entity_listing_service import (
    UnifiedMaskEntityListingService,
)
from arkumu.users.models import Organization

IS_PART_OF_URI = "http://purl.org/dc/terms/isPartOf"


def _create_typed_entity(
    *,
    organization,
    entity_uri,
    type_uri,
    label_predicate_uri,
    label,
):
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={"canonical_uri": type_uri, "resource_type": ResourceType.CLASS},
    )
    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={"canonical_uri": RDF_TYPE_URI, "resource_type": ResourceType.PROPERTY},
    )
    label_predicate, _ = Resource.objects.get_or_create(
        uri=label_predicate_uri,
        defaults={"canonical_uri": label_predicate_uri, "resource_type": ResourceType.PROPERTY},
    )
    entity = Resource.objects.create(
        uri=entity_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value=label,
        organization=organization,
    )
    Triple.objects.create(subject=entity, predicate=rdf_type_resource, object=type_resource, source=organization)
    Triple.objects.create(subject=entity, predicate=label_predicate, object=literal, source=organization)
    return entity


def _create_dataset_membership(*, organization, entity, dataset_uri):
    predicate, _ = Resource.objects.get_or_create(
        uri=IS_PART_OF_URI,
        defaults={"canonical_uri": IS_PART_OF_URI, "resource_type": ResourceType.PROPERTY},
    )
    dataset, _ = Resource.objects.get_or_create(
        uri=dataset_uri,
        defaults={"resource_type": ResourceType.IRI, "organization": organization, "name": dataset_uri.rsplit("/", 1)[-1]},
    )
    Triple.objects.create(subject=entity, predicate=predicate, object=dataset, source=organization)


@pytest.mark.django_db
def test_list_entities_returns_project_records_with_edit_urls():
    organization = Organization.objects.create(name="Folkwang", code="fuk")
    _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/fuk/projects/p1",
        type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uri=CardURIs.TITLE,
        label="Projekt Eins",
    )

    service = UnifiedMaskEntityListingService()
    page = service.list_entities(organization_code="fuk", entity_type="project")

    assert len(page.items) == 1
    assert page.items[0].label == "Projekt Eins"
    assert "edit/project" in (page.items[0].edit_url or "")


@pytest.mark.django_db
def test_list_entities_prefers_mapping_datasets_and_tracks_source_dataset():
    organization = Organization.objects.create(name="HMT", code="hmt")
    Mapping.objects.create(
        name="HMT Produktionen",
        organization_id="hmt",
        mapping_config={
            "schema_manifest": {
                "Produktionen": {
                    "entity_type": {"canonical_uri": CardURIs.PROJECT_TYPE}
                }
            }
        },
    )
    Mapping.objects.create(
        name="HMT Abschlussarbeiten",
        organization_id="hmt",
        mapping_config={
            "promoted_manifest": {
                "schema_manifest": {
                    "Abschlussarbeiten": {
                        "entity_type": {"canonical_uri": CardURIs.PROJECT_TYPE}
                    }
                }
            }
        },
    )

    project_one = _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/hmt/projects/p1",
        type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uri=CardURIs.TITLE,
        label="Produktion Eins",
    )
    project_two = _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/hmt/projects/p2",
        type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uri=CardURIs.TITLE,
        label="Abschlussarbeit Zwei",
    )
    project_fallback = _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/hmt/projects/p3",
        type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uri=CardURIs.TITLE,
        label="Nur Canonical",
    )

    _create_dataset_membership(
        organization=organization,
        entity=project_one,
        dataset_uri="http://arkumu.nrw/data/hmt/datasets/produktionen",
    )
    _create_dataset_membership(
        organization=organization,
        entity=project_two,
        dataset_uri="http://arkumu.nrw/data/hmt/datasets/abschlussarbeiten",
    )

    service = UnifiedMaskEntityListingService()

    page = service.list_entities(organization_code="hmt", entity_type="project")

    assert [item.label for item in page.items] == ["Abschlussarbeit Zwei", "Produktion Eins"]
    assert [item.source_dataset for item in page.items] == ["Abschlussarbeiten", "Produktionen"]
    assert "Nur Canonical" not in {item.label for item in page.items}


@pytest.mark.django_db
def test_list_entities_returns_event_records_with_labels():
    organization = Organization.objects.create(name="HMT", code="hmt")
    _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/hmt/events/e1",
        type_uri=CardURIs.EVENT_TYPE,
        label_predicate_uri=ProjectURIs.EVENT_NAME,
        label="Auffuehrung 1",
    )

    service = UnifiedMaskEntityListingService()
    page = service.list_entities(organization_code="hmt", entity_type="event")

    assert len(page.items) == 1
    assert page.items[0].label == "Auffuehrung 1"


@pytest.mark.django_db
def test_list_entities_returns_paginated_page():
    organization = Organization.objects.create(name="KHM", code="khm")
    for index in range(30):
        _create_typed_entity(
            organization=organization,
            entity_uri=f"http://arkumu.org/data/khm/actors/{index}",
            type_uri=CardURIs.ACTOR_TYPE,
            label_predicate_uri=CardURIs.ACTOR_GERMAN_NAME,
            label=f"Akteur {index}",
        )

    service = UnifiedMaskEntityListingService()
    page = service.list_entities(
        organization_code="khm",
        entity_type="actor",
        page=2,
        per_page=24,
    )

    assert page.page == 2
    assert page.per_page == 24
    assert page.total_count == 30
    assert page.total_pages == 2
    assert page.has_previous is True
    assert page.has_next is False
    assert len(page.items) == 6


@pytest.mark.django_db
def test_list_entities_filters_by_search_query_and_exposes_summary_values():
    organization = Organization.objects.create(name="Folkwang", code="fuk")
    project = _create_typed_entity(
        organization=organization,
        entity_uri="http://arkumu.org/data/fuk/projects/p1",
        type_uri=CardURIs.PROJECT_TYPE,
        label_predicate_uri=CardURIs.TITLE,
        label="Projekt Eins",
    )
    institution_predicate, _ = Resource.objects.get_or_create(
        uri=CardURIs.INSTITUTION,
        defaults={"canonical_uri": CardURIs.INSTITUTION, "resource_type": ResourceType.PROPERTY},
    )
    institution = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/institution/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Folkwang",
    )
    Triple.objects.create(subject=project, predicate=institution_predicate, object=institution, source=organization)

    service = UnifiedMaskEntityListingService()
    page = service.list_entities(
        organization_code="fuk",
        entity_type="project",
        search_query="Folkwang",
    )

    assert page.total_count == 1
    assert page.items[0].label == "Projekt Eins"
    assert "Folkwang" in page.items[0].summary
