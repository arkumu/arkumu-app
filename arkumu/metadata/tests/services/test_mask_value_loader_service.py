import pytest

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.mask_runtime_service import MaskRuntimeService
from arkumu.metadata.services.mask_schema import MappingBindingSource
from arkumu.metadata.services.mask_value_loader_service import MaskValueLoaderService
from arkumu.users.models import Organization


def _mapping_source_with_property_uri(*, organization_code, dataset_name, column_name, property_uri):
    return MappingBindingSource(
        organization_code=organization_code,
        mapping_name=f"{organization_code}-{dataset_name}",
        mapping_id=f"{organization_code}-{dataset_name}",
        mapping_config={
            "workspace_columns": {
                f"{organization_code}::{dataset_name}::{column_name}": {
                    "dataset": dataset_name,
                    "name": column_name,
                    "canonical_mapping": {
                        "canonical_property_uri": CardURIs.TITLE,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            },
            "schema_manifest": {
                dataset_name: {
                    "properties": {
                        column_name: {
                            "uri": property_uri,
                        }
                    }
                }
            },
        },
    )


def _create_literal_triple(*, organization, entity_uri, predicate_uri, predicate_canonical_uri, value):
    entity = Resource.objects.create(
        uri=entity_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    predicate = Resource.objects.create(
        uri=predicate_uri,
        canonical_uri=predicate_canonical_uri,
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value=value,
        organization=organization,
    )
    Triple.objects.create(subject=entity, predicate=predicate, object=literal, source=organization)
    return entity


@pytest.mark.django_db
def test_value_loader_prefers_mapped_property_uri_when_available():
    organization = Organization.objects.create(name="HMT", code="hmt")
    entity = _create_literal_triple(
        organization=organization,
        entity_uri="http://arkumu.org/data/hmt/projects/1",
        predicate_uri="http://arkumu.org/data/hmt/properties/werktitel",
        predicate_canonical_uri=None,
        value="Mapped Title",
    )
    runtime = MaskRuntimeService().resolve(
        entity_type="project",
        organization_code="hmt",
        phase="create",
        mapping_sources=[
            _mapping_source_with_property_uri(
                organization_code="hmt",
                dataset_name="Produktionen",
                column_name="Werktitel",
                property_uri="http://arkumu.org/data/hmt/properties/werktitel",
            )
        ],
    )
    overview = next(section for section in runtime.sections if section.section.name == "overview")
    title_field = next(field for field in overview.fields if field.field.name == "title")

    values = MaskValueLoaderService().load_field_values(
        organization_code="hmt",
        resource_uri=entity.uri,
        fields=[title_field],
    )

    assert values["title"].values == ["Mapped Title"]
    assert values["title"].source_label == "Gemappt"


@pytest.mark.django_db
def test_value_loader_falls_back_to_canonical_predicate():
    organization = Organization.objects.create(name="Folkwang", code="fuk")
    entity = _create_literal_triple(
        organization=organization,
        entity_uri="http://arkumu.org/data/fuk/projects/1",
        predicate_uri=CardURIs.TITLE,
        predicate_canonical_uri=CardURIs.TITLE,
        value="Canonical Title",
    )
    runtime = MaskRuntimeService().resolve(
        entity_type="project",
        organization_code="fuk",
        phase="create",
        mapping_sources=[],
    )
    overview = next(section for section in runtime.sections if section.section.name == "overview")
    title_field = next(field for field in overview.fields if field.field.name == "title")

    values = MaskValueLoaderService().load_field_values(
        organization_code="fuk",
        resource_uri=entity.uri,
        fields=[title_field],
    )

    assert values["title"].values == ["Canonical Title"]
    assert values["title"].source_label == "Canonical"
