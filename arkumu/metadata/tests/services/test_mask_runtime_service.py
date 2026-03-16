from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.services.mask_runtime_service import (
    FIELD_STATE_CANONICAL,
    FIELD_STATE_MAPPED_AND_CANONICAL,
    FIELD_STATE_UNAVAILABLE,
    MaskRuntimeService,
)
from arkumu.metadata.services.mask_schema import MappingBindingSource, build_project_mask_schema


def _mapping_source_for_property(
    *,
    organization_code,
    dataset_name,
    column_name,
    canonical_property_uri,
):
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
                        "canonical_property_uri": canonical_property_uri,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            }
        },
    )


def test_runtime_marks_field_as_mapped_and_canonical_when_binding_exists():
    service = MaskRuntimeService()

    runtime = service.resolve(
        entity_type="project",
        organization_code="hmt",
        phase="create",
        mapping_sources=[
            _mapping_source_for_property(
                organization_code="hmt",
                dataset_name="Produktionen",
                column_name="Werktitel",
                canonical_property_uri=CardURIs.TITLE,
            )
        ],
    )

    title_field = runtime.schema.get_field("title")
    overview = next(section for section in runtime.sections if section.section.name == "overview")
    resolved_title = next(item for item in overview.fields if item.field.name == title_field.name)

    assert resolved_title.state.code == FIELD_STATE_MAPPED_AND_CANONICAL
    assert [(binding.dataset_name, binding.column_name) for binding in resolved_title.bindings] == [
        ("Produktionen", "Werktitel")
    ]


def test_runtime_marks_field_as_canonical_when_no_binding_exists():
    service = MaskRuntimeService()

    runtime = service.resolve(
        entity_type="project",
        organization_code="khm",
        phase="create",
        mapping_sources=[],
    )

    overview = next(section for section in runtime.sections if section.section.name == "overview")
    resolved_title = next(item for item in overview.fields if item.field.name == "title")

    assert resolved_title.state.code == FIELD_STATE_CANONICAL
    assert resolved_title.bindings == []


def test_runtime_marks_field_as_unavailable_without_canonical_slot():
    service = MaskRuntimeService()
    schema = build_project_mask_schema()

    runtime = service.resolve(
        entity_type=schema.entity_type,
        organization_code="fuk",
        phase="enrichment",
        mapping_sources=[],
    )

    overview = next(section for section in runtime.sections if section.section.name == "overview")
    resolved_year_range = next(item for item in overview.fields if item.field.name == "year_range")

    assert resolved_year_range.state.code == FIELD_STATE_UNAVAILABLE
    assert resolved_year_range.bindings == []
