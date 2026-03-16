import pytest

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.unified_mask_workspace_service import UnifiedMaskWorkspaceService
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_workspace_service_lists_all_active_organizations():
    Organization.objects.create(name="Folkwang", code="fuk")
    Organization.objects.create(name="HMT", code="hmt")
    Organization.objects.create(name="KHM", code="khm")

    service = UnifiedMaskWorkspaceService()
    organizations = service.list_organizations()

    assert [organization.code for organization in organizations] == ["fuk", "hmt", "khm"]


@pytest.mark.django_db
def test_workspace_service_builds_create_url_only_for_supported_entities():
    Organization.objects.create(name="Folkwang", code="fuk")

    service = UnifiedMaskWorkspaceService()
    payload = service.build_payload(
        organization_code="fuk",
        entity_type="project",
        phase="create",
        section=None,
        resource_uri=None,
    )

    project_option = next(option for option in payload.entity_options if option.entity_type == "project")
    collection_option = next(option for option in payload.entity_options if option.entity_type == "collection")

    assert project_option.create_url is not None
    assert collection_option.create_url is None


@pytest.mark.django_db
def test_workspace_service_defaults_to_first_available_section():
    Organization.objects.create(name="Folkwang", code="fuk")

    service = UnifiedMaskWorkspaceService()
    payload = service.build_payload(
        organization_code="fuk",
        entity_type="project",
        phase="create",
        section=None,
        resource_uri=None,
    )

    assert payload.selected_section == "overview"


@pytest.mark.django_db
def test_workspace_service_loads_selected_resource_values_for_active_section():
    organization = Organization.objects.create(name="HMT", code="hmt")
    Mapping.objects.create(
        name="HMT Produktionen",
        organization_id="hmt",
        mapping_config={
            "workspace_columns": {
                "hmt::Produktionen::Werktitel": {
                    "dataset": "Produktionen",
                    "name": "Werktitel",
                    "canonical_mapping": {
                        "canonical_property_uri": CardURIs.TITLE,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            },
            "schema_manifest": {
                "Produktionen": {
                    "entity_type": {"canonical_uri": CardURIs.PROJECT_TYPE},
                    "properties": {
                        "Werktitel": {
                            "uri": "http://arkumu.org/data/hmt/properties/werktitel",
                        }
                    },
                }
            },
        },
    )

    entity = Resource.objects.create(
        uri="http://arkumu.org/data/hmt/projects/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    dataset = Resource.objects.create(
        uri="http://arkumu.nrw/data/hmt/datasets/produktionen",
        resource_type=ResourceType.IRI,
        organization=organization,
        name="Produktionen",
    )
    is_part_of = Resource.objects.create(
        uri="http://purl.org/dc/terms/isPartOf",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )
    predicate = Resource.objects.create(
        uri="http://arkumu.org/data/hmt/properties/werktitel",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Mapping Title",
        organization=organization,
    )
    Triple.objects.create(subject=entity, predicate=is_part_of, object=dataset, source=organization)
    Triple.objects.create(subject=entity, predicate=predicate, object=literal, source=organization)

    service = UnifiedMaskWorkspaceService()
    payload = service.build_payload(
        organization_code="hmt",
        entity_type="project",
        phase="create",
        section="overview",
        resource_uri=entity.uri,
    )

    assert payload.selected_resource_uri == entity.uri
    assert payload.selected_resource_label == entity.uri.rsplit("/", 1)[-1]
    assert payload.selected_resource_values["title"].values == ["Mapping Title"]
    assert payload.selected_resource_values["title"].source_label == "Gemappt"


@pytest.mark.django_db
def test_workspace_service_exposes_paginated_existing_entities():
    organization = Organization.objects.create(name="KHM", code="khm")
    actor_type = Resource.objects.create(
        uri=CardURIs.ACTOR_TYPE,
        canonical_uri=CardURIs.ACTOR_TYPE,
        resource_type=ResourceType.CLASS,
        organization=organization,
    )
    rdf_type = Resource.objects.create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        canonical_uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )
    name_prop = Resource.objects.create(
        uri=CardURIs.ACTOR_GERMAN_NAME,
        canonical_uri=CardURIs.ACTOR_GERMAN_NAME,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )
    for index in range(30):
        actor = Resource.objects.create(
            uri=f"http://arkumu.org/data/khm/actors/{index}",
            resource_type=ResourceType.ENTITY,
            organization=organization,
        )
        literal = Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=f"Akteur {index}",
            organization=organization,
        )
        Triple.objects.create(subject=actor, predicate=rdf_type, object=actor_type, source=organization)
        Triple.objects.create(subject=actor, predicate=name_prop, object=literal, source=organization)

    payload = UnifiedMaskWorkspaceService().build_payload(
        organization_code="khm",
        entity_type="actor",
        phase="create",
        section=None,
        resource_uri=None,
        page=2,
    )

    assert payload.existing_entities_page.page == 2
    assert payload.existing_entities_page.total_count == 30
    assert payload.existing_entities_page.total_pages == 2
    assert len(payload.existing_entities) == 6
    assert payload.selected_resource_uri is None
