"""
Tests for FK resolution and serialization fixes.

This suite verifies two key behaviors:
- ConfigTranslator extracts source dataset/column from FK keys when missing.
- CSVMappingCoordinatorMixin serialization includes source info in fk_relationships.
"""

import pytest
from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware

from arkumu.importer.services.mapping_consumer.config_translator import (
    ConfigTranslator,
    ColumnType,
)
from arkumu.metadata.views.csv_mapping.mixins.coordinator import (
    CSVMappingCoordinatorMixin,
)


def _add_session(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    return request


@pytest.mark.django_db
def test_config_translator_extracts_source_from_fk_key_with_org():
    """ConfigTranslator should parse source info from 'org::dataset::column' keys."""
    mapping_config = {
        "_metadata": {
            "mapping_id": 1,
            "mapping_name": "FUK Test Mapping",
            "organization": "fuk",
        },
        "workspace_datasets": ["Projekt", "Ereignis"],
        "workspace_columns": {
            # Qualified key format used in workspace_columns
            "fuk::Projekt::Ereignis": {
                "arkumu_type": "Ereignis",
                "is_fk": True,
                "fk_config": {
                    "target_dataset": "Ereignis",
                    "target_column": "Ereignis-ID",
                    "direction": "outbound",
                    "relationship_type": "relatedTo",
                },
            }
        },
        "fk_relationships": {
            # Problematic structure missing source info in the value
            "fuk::Projekt::Ereignis": {
                "target_dataset": "Ereignis",
                "target_column": "Ereignis-ID",
            }
        },
    }

    translator = ConfigTranslator()
    execution = translator.translate_mapping_config(mapping_config)

    assert len(execution.fk_relationships) == 1
    fk = execution.fk_relationships[0]
    assert fk.source_dataset == "Projekt"
    assert fk.source_column == "Ereignis"
    assert fk.target_dataset == "Ereignis"
    assert fk.target_column == "Ereignis-ID"

    # Column type should be marked as FOREIGN_KEY
    col_key = "Projekt.Ereignis"
    assert col_key in execution.column_configurations
    assert execution.column_configurations[col_key].column_type == ColumnType.FOREIGN_KEY


@pytest.mark.django_db
def test_config_translator_extracts_source_from_fk_key_legacy_two_parts():
    """Also support legacy 'dataset::column' keys without organization prefix."""
    mapping_config = {
        "_metadata": {
            "mapping_id": 2,
            "mapping_name": "Legacy Format Mapping",
            "organization": "legacy",
        },
        "workspace_datasets": ["Projekt", "Ereignis"],
        "workspace_columns": {
            # Even if workspace uses qualified keys, the FK dict may be legacy two-part
            "legacy::Projekt::Ereignis": {
                "arkumu_type": "Ereignis",
                "is_fk": True,
                "fk_config": {
                    "target_dataset": "Ereignis",
                    "target_column": "Ereignis-ID",
                },
            }
        },
        "fk_relationships": {
            # Legacy two-part key (no org)
            "Projekt::Ereignis": {
                "target_dataset": "Ereignis",
                "target_column": "Ereignis-ID",
            }
        },
    }

    translator = ConfigTranslator()
    execution = translator.translate_mapping_config(mapping_config)

    assert len(execution.fk_relationships) == 1
    fk = execution.fk_relationships[0]
    assert fk.source_dataset == "Projekt"
    assert fk.source_column == "Ereignis"
    assert fk.target_dataset == "Ereignis"
    assert fk.target_column == "Ereignis-ID"


@pytest.mark.django_db
def test_coordinator_serialization_includes_source_info_in_fk_relationships():
    """
    CSVMappingCoordinatorMixin.serialize_current_mapping_state should include
    source_dataset and source_column in fk_relationships values.
    """
    coordinator = CSVMappingCoordinatorMixin()
    rf = RequestFactory()
    request = _add_session(rf.get("/"))

    organization_id = 123  # We can use any numeric org id for session keys

    # Prepare a workspace column representing an FK
    column_id = "fuk::Projekt::Ereignis"
    workspace_column = {
        "id": column_id,
        "name": "Ereignis",
        "dataset": "Projekt",
        "source": "fuk",
        "type": "string",
        "is_fk": True,
        "fk_config": {
            "target_dataset": "Ereignis",
            "target_column": "Ereignis-ID",
            "relationship_type": "relatedTo",
            "direction": "outbound",
        },
    }

    # Store in the session using the same key logic as the coordinator
    session_key = coordinator.get_session_key("workspace_columns", organization_id)
    request.session[session_key] = [workspace_column]
    request.session.save()

    mapping = coordinator.serialize_current_mapping_state(request, organization_id, mapping_name="Test Mapping")

    assert "fk_relationships" in mapping
    assert column_id in mapping["fk_relationships"]
    fk_entry = mapping["fk_relationships"][column_id]

    # New fields must be present
    assert fk_entry.get("source_dataset") == "Projekt"
    assert fk_entry.get("source_column") == "Ereignis"
    # Existing fields unchanged
    assert fk_entry.get("target_dataset") == "Ereignis"
    assert fk_entry.get("target_column") == "Ereignis-ID"

