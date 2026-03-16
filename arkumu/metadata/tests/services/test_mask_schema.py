from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.services.mask_schema import (
    MappingBindingSource,
    MappingConfigBindingResolver,
    build_event_mask_schema,
    build_project_mask_schema,
    field_is_visible_in_phase,
)


def test_build_project_mask_schema_exposes_sections_and_required_title():
    schema = build_project_mask_schema()

    assert schema.entity_type == "project"
    assert [section.name for section in schema.sections] == [
        "overview",
        "institution",
        "classification",
    ]

    title_field = schema.get_field("title")
    assert title_field.required_rule.is_required is True
    assert title_field.required_rule.frontend_grails_required is True
    assert title_field.required_rule.backend_grails_required is True
    assert title_field.required_rule.frontend_grails_label == "ja"
    assert title_field.required_rule.backend_grails_label == "ja"
    assert title_field.semantic_slot.canonical_property_uri == CardURIs.TITLE

    subtitle_field = schema.get_field("subtitle")
    assert subtitle_field.required_rule.frontend_grails_required is False
    assert subtitle_field.required_rule.backend_grails_required is False

    project_type_field = schema.get_field("project_type")
    assert project_type_field.semantic_slot.canonical_property_uri == ProjectURIs.PROJECT_TYPE_FIELD
    assert project_type_field.vocabulary is not None
    assert project_type_field.vocabulary.key == "project_type"
    assert field_is_visible_in_phase(title_field, "create") is True
    assert field_is_visible_in_phase(subtitle_field, "create") is False
    assert field_is_visible_in_phase(subtitle_field, "enrichment") is True


def test_mapping_binding_resolver_collects_bindings_from_multiple_mappings():
    resolver = MappingConfigBindingResolver()
    mapping_sources = [
        MappingBindingSource(
            organization_code="khm",
            mapping_name="mapping-a",
            mapping_id="a",
            mapping_config={
                "workspace_columns": {
                    "khm::00_Projekte::Titel": {
                        "dataset": "00_Projekte",
                        "name": "Titel",
                        "is_multi_value": False,
                        "canonical_mapping": {
                            "canonical_property_uri": CardURIs.TITLE,
                            "canonical_property_label": "Bevorzugter Titel",
                        },
                    }
                }
            },
        ),
        MappingBindingSource(
            organization_code="khm",
            mapping_name="mapping-b",
            mapping_id="b",
            mapping_config={
                "workspace_columns": {
                    "khm::01_Grundereignis::Titel des Projekts": {
                        "dataset": "01_Grundereignis",
                        "name": "Titel des Projekts",
                        "is_multi_value": False,
                        "canonical_mapping": {
                            "canonical_property_uri": CardURIs.TITLE,
                            "canonical_property_label": "Bevorzugter Titel",
                        },
                    }
                }
            },
        ),
    ]

    bindings = resolver.resolve_canonical_property(
        canonical_property_uri=CardURIs.TITLE,
        organization_code="khm",
        mapping_sources=mapping_sources,
    )

    assert {(binding.mapping_name, binding.dataset_name, binding.column_name) for binding in bindings} == {
        ("mapping-a", "00_Projekte", "Titel"),
        ("mapping-b", "01_Grundereignis", "Titel des Projekts"),
    }


def test_build_event_mask_schema_exposes_grails_requiredness_and_vocab():
    schema = build_event_mask_schema()

    assert schema.entity_type == "event"
    assert [section.name for section in schema.sections] == [
        "overview",
        "dates",
    ]

    event_type_field = schema.get_field("event_type")
    assert event_type_field.required_rule.is_required is True
    assert event_type_field.required_rule.frontend_grails_required is True
    assert event_type_field.required_rule.backend_grails_required is True
    assert event_type_field.semantic_slot.canonical_property_uri == ProjectURIs.EVENT_TYPE
    assert event_type_field.vocabulary is not None
    assert event_type_field.vocabulary.key == "event_types"
    assert field_is_visible_in_phase(event_type_field, "create") is True

    start_field = schema.get_field("start")
    assert start_field.required_rule.is_required is False
    assert start_field.required_rule.frontend_grails_required is False
    assert start_field.required_rule.backend_grails_required is False
    assert "Datumsformat" in (start_field.required_rule.source_detail or "")
    assert field_is_visible_in_phase(start_field, "create") is False
    assert field_is_visible_in_phase(start_field, "enrichment") is True
