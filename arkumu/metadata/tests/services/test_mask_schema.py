import pytest

from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.mask_schema import (
    MappingBindingSource,
    MappingConfigBindingResolver,
    build_actor_mask_schema,
    build_event_mask_schema,
    build_place_mask_schema,
    build_project_mask_schema,
    field_is_visible_in_phase,
    load_mapping_sources_for_organization,
    list_available_mask_schemas,
    list_creatable_mask_schemas,
)
from arkumu.users.models import Organization


def _mapping_source_for_property(
    *,
    organization_code,
    mapping_name,
    dataset_name,
    column_name,
    canonical_property_uri,
    canonical_property_label,
):
    return MappingBindingSource(
        organization_code=organization_code,
        mapping_name=mapping_name,
        mapping_id=mapping_name,
        mapping_config={
            "workspace_columns": {
                f"{organization_code}::{dataset_name}::{column_name}": {
                    "dataset": dataset_name,
                    "name": column_name,
                    "is_multi_value": False,
                    "canonical_mapping": {
                        "canonical_property_uri": canonical_property_uri,
                        "canonical_property_label": canonical_property_label,
                    },
                }
            }
        },
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


def test_project_mask_stays_unified_while_bindings_vary_by_institution():
    schema = build_project_mask_schema()
    title_field = schema.get_field("title")
    resolver = MappingConfigBindingResolver()
    mapping_sources = [
        _mapping_source_for_property(
            organization_code="fuk",
            mapping_name="fuk-projects",
            dataset_name="00_Projekte",
            column_name="Titel",
            canonical_property_uri=CardURIs.TITLE,
            canonical_property_label="Bevorzugter Titel",
        ),
        _mapping_source_for_property(
            organization_code="hmt",
            mapping_name="hmt-productions",
            dataset_name="Produktionen",
            column_name="Werktitel",
            canonical_property_uri=CardURIs.TITLE,
            canonical_property_label="Bevorzugter Titel",
        ),
        _mapping_source_for_property(
            organization_code="khm",
            mapping_name="khm-works",
            dataset_name="Werke",
            column_name="Bezeichnung",
            canonical_property_uri=CardURIs.TITLE,
            canonical_property_label="Bevorzugter Titel",
        ),
    ]

    assert title_field.label == "Titel"
    assert title_field.semantic_slot.slot_id == "project.preferred_title"
    assert title_field.semantic_slot.canonical_property_uri == CardURIs.TITLE

    fuk_bindings = resolver.resolve_field_bindings(
        field=title_field,
        organization_code="fuk",
        mapping_sources=mapping_sources,
    )
    hmt_bindings = resolver.resolve_field_bindings(
        field=title_field,
        organization_code="hmt",
        mapping_sources=mapping_sources,
    )
    khm_bindings = resolver.resolve_field_bindings(
        field=title_field,
        organization_code="khm",
        mapping_sources=mapping_sources,
    )

    assert [(binding.dataset_name, binding.column_name) for binding in fuk_bindings] == [
        ("00_Projekte", "Titel")
    ]
    assert [(binding.dataset_name, binding.column_name) for binding in hmt_bindings] == [
        ("Produktionen", "Werktitel")
    ]
    assert [(binding.dataset_name, binding.column_name) for binding in khm_bindings] == [
        ("Werke", "Bezeichnung")
    ]


@pytest.mark.django_db
def test_load_mapping_sources_for_organization_returns_only_requested_org_mappings():
    Organization.objects.create(name="Folkwang", code="fuk")
    Organization.objects.create(name="HMT", code="hmt")
    Organization.objects.create(name="KHM", code="khm")

    Mapping.objects.create(
        name="Folkwang Projects",
        organization_id="fuk",
        mapping_config={
            "workspace_columns": {
                "fuk::00_Projekte::Titel": {
                    "dataset": "00_Projekte",
                    "name": "Titel",
                    "canonical_mapping": {
                        "canonical_property_uri": CardURIs.TITLE,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            }
        },
    )
    Mapping.objects.create(
        name="HMT Productions",
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
            }
        },
    )
    Mapping.objects.create(
        name="KHM Works",
        organization_id="khm",
        mapping_config={
            "workspace_columns": {
                "khm::Werke::Bezeichnung": {
                    "dataset": "Werke",
                    "name": "Bezeichnung",
                    "canonical_mapping": {
                        "canonical_property_uri": CardURIs.TITLE,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            }
        },
    )

    hmt_sources = load_mapping_sources_for_organization("hmt")

    assert [(source.organization_code, source.mapping_name) for source in hmt_sources] == [
        ("hmt", "HMT Productions")
    ]
    assert hmt_sources[0].mapping_config["workspace_columns"]["hmt::Produktionen::Werktitel"]["name"] == "Werktitel"


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

    name_field = schema.get_field("name")
    assert name_field.required_rule.is_required is False
    assert name_field.required_rule.frontend_grails_required is False
    assert name_field.required_rule.backend_grails_required is False
    assert field_is_visible_in_phase(name_field, "create") is True

    start_field = schema.get_field("start")
    assert start_field.required_rule.is_required is False
    assert start_field.required_rule.frontend_grails_required is False
    assert start_field.required_rule.backend_grails_required is False
    assert "Datumsformat" in (start_field.required_rule.source_detail or "")
    assert field_is_visible_in_phase(start_field, "create") is False
    assert field_is_visible_in_phase(start_field, "enrichment") is True


def test_list_available_and_creatable_masks_are_separated():
    available = {schema.entity_type for schema in list_available_mask_schemas()}
    creatable = {schema.entity_type for schema in list_creatable_mask_schemas()}

    assert {
        "project",
        "event",
        "actor",
        "place",
        "collection",
        "information_carrier",
        "keyword",
        "digital_object",
    }.issubset(available)
    assert creatable == {"project", "event", "actor"}


def test_build_actor_mask_schema_supports_conditional_name_rule():
    schema = build_actor_mask_schema()

    assert schema.entity_type == "actor"
    assert schema.create_supported is True
    name_de = schema.get_field("name_de")
    name_en = schema.get_field("name_en")

    assert name_de.required_rule.kind == "conditional"
    assert name_en.required_rule.kind == "conditional"
    assert "mindestens eines" in (name_de.required_rule.source_detail or "").lower()
    assert name_de.semantic_slot.canonical_property_uri == CardURIs.ACTOR_GERMAN_NAME


def test_build_place_mask_schema_marks_coordinate_gap():
    schema = build_place_mask_schema()

    assert schema.entity_type == "place"
    assert schema.create_supported is False
    latitude = schema.get_field("latitude")

    assert latitude.required_rule.is_required is True
    assert latitude.semantic_slot.canonical_property_uri is None
    assert "canonical model" in (latitude.required_rule.source_detail or "").lower()
