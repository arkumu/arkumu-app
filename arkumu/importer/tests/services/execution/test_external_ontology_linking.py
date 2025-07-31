"""
Tests for external ontology linking with specific property instances.

Tests the creation of specific property instance IRIs and their linking
to external ontologies (Wikidata, ORCID, etc.) via owl:sameAs relationships.
"""
import pytest
from unittest.mock import Mock, patch, call
from dataclasses import dataclass

from arkumu.importer.services.execution.mapping_aware_processor import (
    MappingAwareProcessor, ProcessingContext
)
from arkumu.importer.services.mapping_consumer import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType, ProcessingStrategy
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics, ExecutionMetrics
from arkumu.metadata.models import Resource, ResourceType
from arkumu.metadata.models.triples import Triple


def create_mock_resource(resource_id=1, uri="test://resource", resource_type=ResourceType.IRI):
    """Helper function to create properly mocked Django Resource instances"""
    mock_resource = Mock(spec=Resource)
    mock_resource.id = resource_id
    mock_resource.uri = uri
    mock_resource.resource_type = resource_type
    mock_resource._meta = Resource._meta
    mock_resource._state = Mock()
    mock_resource._state.db = 'default'
    return mock_resource


@pytest.mark.django_db
class TestExternalOntologyLinking:
    """Test suite for external ontology linking with specific property instances"""
    
    def test_external_ontology_creates_literal_and_links_external(self, test_organization, test_base_uri, execution_statistics):
        """Test that external ontology columns create normal property triples and link external ontology to literal"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create column config for Wikidata QID
        wikidata_column = ColumnConfig(
            column_name="ort_wikidata_qid",
            dataset_name="test_dataset",
            arkumu_type="ort-wikidata-qid",
            is_external_ontology=True,
            external_ontology_config={
                'ontology_type': 'wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}'
            }
        )
        
        # Mock entity resource
        entity_resource = create_mock_resource(1, "http://test.org/entity/123")
        
        # Test data
        row_data = {"ort_wikidata_qid": "Q60"}  # New York City
        
        # Mock the resource manager methods
        literal_resource = create_mock_resource(2, "http://test.org/literal/Q60")
        external_resource = create_mock_resource(3, "https://www.wikidata.org/entity/Q60")
        
        # Mock triple with object pointing to literal resource
        mock_triple = Mock(spec=Triple)
        mock_triple.object = literal_resource
        
        with patch.object(processor.resource_manager, 'create_property_triple') as mock_create_prop:
            with patch.object(processor.resource_manager, 'create_external_resource') as mock_create_ext:
                with patch.object(processor.resource_manager, 'create_owl_same_as_triple') as mock_create_sameas:
                    
                    # Configure mocks
                    mock_create_prop.return_value = mock_triple
                    mock_create_ext.return_value = external_resource
                    
                    # Process the column
                    processor._process_external_ontology_columns(
                        entity_resource, 
                        row_data, 
                        [wikidata_column], 
                        ProcessingContext(
                            execution_config=Mock(),
                            current_dataset="test_dataset",
                            all_csv_sources={},
                            entity_cache={},
                            processed_datasets=set()
                        )
                    )
                    
                    # Verify normal property triple was created (entity -> property -> literal)
                    mock_create_prop.assert_called_with(
                        entity_resource,
                        f"{test_base_uri}/{test_organization.code}/properties/ort-wikidata-qid",
                        "Q60",
                        "http://www.w3.org/2001/XMLSchema#string"
                    )
                    
                    # Verify external resource creation
                    mock_create_ext.assert_called_with(
                        "https://www.wikidata.org/entity/Q60",
                        "wikidata"
                    )
                    
                    # Verify owl:sameAs links external ontology to literal resource
                    mock_create_sameas.assert_called_with(
                        external_resource,
                        literal_resource
                    )
    
    def test_multiple_entities_with_same_external_id(self, test_organization, test_base_uri, execution_statistics):
        """Test that multiple entities can reference the same external ontology ID"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create column config
        wikidata_column = ColumnConfig(
            column_name="location_qid",
            dataset_name="test_dataset",
            arkumu_type="ort-wikidata-qid",
            is_external_ontology=True,
            external_ontology_config={
                'ontology_type': 'wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}'
            }
        )
        
        # Two different entities with same Wikidata QID
        entity1 = create_mock_resource(1, "http://test.org/entity/event1")
        entity2 = create_mock_resource(2, "http://test.org/entity/event2")
        
        row_data = {"location_qid": "Q64"}  # Berlin
        
        # Mock resources for literals and external
        literal_resource1 = create_mock_resource(3, "http://test.org/literal/Q64-1")
        literal_resource2 = create_mock_resource(4, "http://test.org/literal/Q64-2")
        external_resource = create_mock_resource(5, "https://www.wikidata.org/entity/Q64")
        
        # Mock triples
        mock_triple1 = Mock(spec=Triple)
        mock_triple1.object = literal_resource1
        mock_triple2 = Mock(spec=Triple)
        mock_triple2.object = literal_resource2
        
        with patch.object(processor.resource_manager, 'create_property_triple') as mock_create_prop:
            with patch.object(processor.resource_manager, 'create_external_resource') as mock_create_ext:
                with patch.object(processor.resource_manager, 'create_owl_same_as_triple') as mock_create_sameas:
                    
                    # Return different triples for each entity
                    mock_create_prop.side_effect = [mock_triple1, mock_triple2]
                    mock_create_ext.return_value = external_resource
                    
                    context = ProcessingContext(
                        execution_config=Mock(),
                        current_dataset="test_dataset",
                        all_csv_sources={},
                        entity_cache={},
                        processed_datasets=set()
                    )
                    
                    # Process for both entities
                    processor._process_external_ontology_columns(entity1, row_data, [wikidata_column], context)
                    processor._process_external_ontology_columns(entity2, row_data, [wikidata_column], context)
                    
                    # Verify both entities created property triples
                    expected_prop_calls = [
                        call(
                            entity1,
                            f"{test_base_uri}/{test_organization.code}/properties/ort-wikidata-qid",
                            "Q64",
                            "http://www.w3.org/2001/XMLSchema#string"
                        ),
                        call(
                            entity2,
                            f"{test_base_uri}/{test_organization.code}/properties/ort-wikidata-qid",
                            "Q64",
                            "http://www.w3.org/2001/XMLSchema#string"
                        )
                    ]
                    mock_create_prop.assert_has_calls(expected_prop_calls)
                    
                    # Verify both literal resources are linked to same external resource
                    expected_sameas_calls = [
                        call(external_resource, literal_resource1),
                        call(external_resource, literal_resource2)
                    ]
                    mock_create_sameas.assert_has_calls(expected_sameas_calls)
    
    def test_different_external_ontology_types(self, test_organization, test_base_uri, execution_statistics):
        """Test handling of different external ontology types (ORCID, Wikidata, etc.)"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Multiple external ontology columns
        columns = [
            ColumnConfig(
                column_name="author_orcid",
                dataset_name="test_dataset",
                arkumu_type="person-orcid",
                is_external_ontology=True,
                external_ontology_config={
                    'ontology_type': 'orcid',
                    'uri_template': 'https://orcid.org/{identifier}'
                }
            ),
            ColumnConfig(
                column_name="subject_wikidata",
                dataset_name="test_dataset",
                arkumu_type="subject-wikidata-qid",
                is_external_ontology=True,
                external_ontology_config={
                    'ontology_type': 'wikidata',
                    'uri_template': 'https://www.wikidata.org/entity/{identifier}'
                }
            )
        ]
        
        entity_resource = create_mock_resource(1, "http://test.org/entity/publication1")
        row_data = {
            "author_orcid": "0000-0002-1825-0097",
            "subject_wikidata": "Q395"  # Mathematics
        }
        
        # Mock literal and external resources
        orcid_literal = create_mock_resource(2, "http://test.org/literal/orcid/0000-0002-1825-0097")
        wikidata_literal = create_mock_resource(3, "http://test.org/literal/wikidata/Q395")
        orcid_external = create_mock_resource(4, "https://orcid.org/0000-0002-1825-0097")
        wikidata_external = create_mock_resource(5, "https://www.wikidata.org/entity/Q395")
        
        # Mock triples
        orcid_triple = Mock(spec=Triple)
        orcid_triple.object = orcid_literal
        wikidata_triple = Mock(spec=Triple)
        wikidata_triple.object = wikidata_literal
        
        with patch.object(processor.resource_manager, 'create_property_triple') as mock_create_prop:
            with patch.object(processor.resource_manager, 'create_external_resource') as mock_create_ext:
                with patch.object(processor.resource_manager, 'create_owl_same_as_triple') as mock_create_sameas:
                    
                    # Return different triples for each column
                    mock_create_prop.side_effect = [orcid_triple, wikidata_triple]
                    
                    def external_side_effect(uri, ontology_type):
                        if "orcid.org" in uri:
                            return orcid_external
                        elif "wikidata.org" in uri:
                            return wikidata_external
                        return Mock()
                    
                    mock_create_ext.side_effect = external_side_effect
                    
                    # Process columns
                    processor._process_external_ontology_columns(
                        entity_resource,
                        row_data,
                        columns,
                        ProcessingContext(
                            execution_config=Mock(),
                            current_dataset="test_dataset",
                            all_csv_sources={},
                            entity_cache={},
                            processed_datasets=set()
                        )
                    )
                    
                    # Verify property triples were created
                    expected_prop_calls = [
                        call(
                            entity_resource,
                            f"{test_base_uri}/{test_organization.code}/properties/person-orcid",
                            "0000-0002-1825-0097",
                            "http://www.w3.org/2001/XMLSchema#string"
                        ),
                        call(
                            entity_resource,
                            f"{test_base_uri}/{test_organization.code}/properties/subject-wikidata-qid",
                            "Q395",
                            "http://www.w3.org/2001/XMLSchema#string"
                        )
                    ]
                    mock_create_prop.assert_has_calls(expected_prop_calls, any_order=True)
                    
                    # Verify external ontology links to literal resources
                    expected_sameas_calls = [
                        call(orcid_external, orcid_literal),
                        call(wikidata_external, wikidata_literal)
                    ]
                    mock_create_sameas.assert_has_calls(expected_sameas_calls, any_order=True)
    
    def test_empty_external_ontology_value_skipped(self, test_organization, test_base_uri, execution_statistics):
        """Test that empty external ontology values are skipped"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        column = ColumnConfig(
            column_name="wikidata_id",
            dataset_name="test_dataset",
            arkumu_type="wikidata-qid",
            is_external_ontology=True,
            external_ontology_config={
                'ontology_type': 'wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}'
            }
        )
        
        entity_resource = create_mock_resource(1, "http://test.org/entity/123")
        
        # Test various empty values
        empty_values = [
            {"wikidata_id": ""},
            {"wikidata_id": None},
            {"wikidata_id": "   "},  # Just whitespace
            {}  # Missing key
        ]
        
        with patch.object(processor.resource_manager, 'create_property_triple') as mock_create_prop:
            with patch.object(processor.resource_manager, 'create_external_resource') as mock_create_ext:
                with patch.object(processor.resource_manager, 'create_owl_same_as_triple') as mock_create_sameas:
                    
                    for row_data in empty_values:
                        processor._process_external_ontology_columns(
                            entity_resource,
                            row_data,
                            [column],
                            ProcessingContext(
                                execution_config=Mock(),
                                current_dataset="test_dataset",
                                all_csv_sources={},
                                entity_cache={},
                                processed_datasets=set()
                            )
                        )
                    
                    # Should not create any property triples or external resources for empty values
                    mock_create_prop.assert_not_called()
                    mock_create_ext.assert_not_called()
                    mock_create_sameas.assert_not_called()
    
    def test_integration_with_real_data_flow(self, test_organization, test_base_uri, execution_statistics):
        """Integration test focuses on external ontology linking during entity processing"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create column config for external ontology
        external_column = ColumnConfig(
            column_name="location_wikidata",
            dataset_name="events",
            arkumu_type="ort-wikidata-qid",
            is_external_ontology=True,
            external_ontology_config={
                'ontology_type': 'wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}'
            }
        )
        
        # Mock entity and resources
        entity_resource = create_mock_resource(1, f"{test_base_uri}/entities/events/11436")
        literal_resource = create_mock_resource(2, f"{test_base_uri}/literal/q8818")
        external_resource = create_mock_resource(3, "https://www.wikidata.org/entity/Q8818")
        
        # Mock triple
        mock_triple = Mock(spec=Triple)
        mock_triple.object = literal_resource
        
        # Test data
        row_data = {
            "event_id": "11436",
            "event_name": "Art Exhibition",
            "location_wikidata": "Q8818"  # Valencia
        }
        
        with patch.object(processor.resource_manager, 'create_property_triple') as mock_create_prop:
            with patch.object(processor.resource_manager, 'create_external_resource') as mock_create_ext:
                with patch.object(processor.resource_manager, 'create_owl_same_as_triple') as mock_create_sameas:
                    
                    # Configure mocks
                    mock_create_prop.return_value = mock_triple
                    mock_create_ext.return_value = external_resource
                    
                    # Call the specific method we're testing
                    processor._process_external_ontology_columns(
                        entity_resource,
                        row_data,
                        [external_column],
                        ProcessingContext(
                            execution_config=Mock(),
                            current_dataset="events",
                            all_csv_sources={},
                            entity_cache={},
                            processed_datasets=set()
                        )
                    )
                    
                    # Verify normal property triple was created
                    mock_create_prop.assert_called_with(
                        entity_resource,
                        f"{test_base_uri}/{test_organization.code}/properties/ort-wikidata-qid",
                        "Q8818",
                        "http://www.w3.org/2001/XMLSchema#string"
                    )
                    
                    # Verify external resource creation
                    mock_create_ext.assert_called_with(
                        "https://www.wikidata.org/entity/Q8818",
                        "wikidata"
                    )
                    
                    # Verify external ontology links to literal resource
                    mock_create_sameas.assert_called_with(
                        external_resource,
                        literal_resource
                    )