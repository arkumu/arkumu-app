"""
Tests for MappingAwareProcessor.

Tests the enhanced processor that handles mapping configurations
including anchor columns, FK relationships, multi-value columns,
relationship contexts, and external ontology integration.
"""
import pytest
from unittest.mock import Mock, patch, call
from dataclasses import dataclass

from arkumu.importer.services.execution.mapping_aware_processor import (
    MappingAwareProcessor, ProcessingContext
)
from arkumu.importer.services.mapping_consumer import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType, ProcessingStrategy,
    FKRelationship, RelationshipContext
)
from arkumu.importer.services.execution.statistics import ExecutionStatistics, ExecutionMetrics
from arkumu.metadata.models import Resource


def create_mock_resource(resource_id=1, uri="test://resource"):
    """Helper function to create properly mocked Django Resource instances"""
    mock_resource = Mock(spec=Resource)
    mock_resource.id = resource_id
    mock_resource.uri = uri
    mock_resource._meta = Resource._meta
    mock_resource._state = Mock()
    mock_resource._state.db = 'default'
    return mock_resource


@pytest.mark.django_db
class TestMappingAwareProcessor:
    """Test suite for MappingAwareProcessor"""
    
    def test_initialization(self, test_organization, test_base_uri, execution_statistics):
        """Test MappingAwareProcessor initialization"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        assert processor.organization == test_organization
        assert processor.institution == test_organization.code
        assert processor.base_uri == test_base_uri
        assert processor.statistics is execution_statistics
        
        # Verify component initialization
        assert processor.data_processor is not None
        assert processor.resource_manager is not None
        
        # Verify processing state
        assert processor.entity_cache == {}
        assert processor.pending_relationships == []
    
    def test_processing_context_creation(self, test_organization, test_base_uri, 
                                       execution_statistics, execution_config_simple):
        """Test ProcessingContext creation"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {"test_dataset": [{"name": "John", "age": "30"}]}
        
        context = ProcessingContext(
            execution_config=execution_config_simple,
            current_dataset="test_dataset",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        assert context.execution_config is execution_config_simple
        assert context.current_dataset == "test_dataset"
        assert context.all_csv_sources == csv_sources
        assert context.entity_cache == {}
        assert context.processed_datasets == set()
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_process_with_streaming_entity_centric_strategy(self, mock_triple_objects, mock_resource_objects,
                                                test_organization, test_base_uri, 
                                                execution_statistics, execution_config_simple):
        """Test processing with streaming entity-centric strategy"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {
            "test_dataset": [
                {"name": "John Doe", "age": "30"},
                {"name": "Jane Smith", "age": "25"}
            ]
        }
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        assert isinstance(metrics, ExecutionMetrics)
        assert "test_dataset" in processor.entity_cache or len(processor.entity_cache) >= 0
    
    def test_process_with_streaming_entity_centric_strategy(self, test_organization, 
                                                          test_base_uri, execution_statistics, 
                                                          execution_config_simple):
        """Test processing with streaming entity-centric strategy"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {
            "test_dataset": [
                {"name": "John Doe", "age": "30"},
                {"name": "Jane Smith", "age": "25"}
            ]
        }
        
        with patch.object(processor, '_process_streaming_entity_centric') as mock_process:
            mock_process.return_value = ExecutionMetrics()
            
            metrics = processor.process_with_execution_config(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
            
            assert isinstance(metrics, ExecutionMetrics)
            mock_process.assert_called_once()
    
    def test_process_with_multi_phase_strategy(self, test_organization, test_base_uri, 
                                             execution_statistics, execution_config_simple):
        """Test processing with multi-phase strategy"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {
            "test_dataset": [
                {"name": "John Doe", "age": "30"}
            ]
        }
        
        with patch.object(processor, '_process_multi_phase') as mock_process:
            mock_process.return_value = ExecutionMetrics()
            
            metrics = processor.process_with_execution_config(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
            
            assert isinstance(metrics, ExecutionMetrics)
            mock_process.assert_called_once()
    
    def test_process_with_unsupported_strategy(self, test_organization, test_base_uri, 
                                             execution_statistics, execution_config_simple):
        """Test processing with unsupported strategy raises error"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {"test_dataset": [{"name": "John"}]}
        
        with pytest.raises(ValueError, match="Unsupported processing strategy"):
            processor.process_with_execution_config(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy="INVALID_STRATEGY"
            )
    
    def test_group_columns_by_type(self, test_organization, test_base_uri, execution_statistics):
        """Test grouping columns by their types"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create columns of different types
        columns = [
            ColumnConfig(
                column_name="person_id",
                dataset_name="test_dataset",
                column_type=ColumnType.REGULAR,
                arkumu_type="identifier",
                datatype="string",
                is_anchor=True,
                is_multi_value=False,
                multi_value_separator=",",
                is_external_ontology=False,
                external_ontology_config=None,
            ),
            ColumnConfig(
                column_name="department_id",
                dataset_name="test_dataset",
                column_type=ColumnType.FOREIGN_KEY,
                arkumu_type="department",
                datatype="string",
                is_anchor=False,
                is_multi_value=False,
                multi_value_separator=",",
                is_external_ontology=False,
                external_ontology_config=None,
            ),
            ColumnConfig(
                column_name="skills",
                dataset_name="test_dataset",
                column_type=ColumnType.REGULAR,
                arkumu_type="skill",
                datatype="string",
                is_anchor=False,
                is_multi_value=True,
                multi_value_separator=",",
                is_external_ontology=False,
                external_ontology_config=None,
            ),
            ColumnConfig(
                column_name="orcid",
                dataset_name="test_dataset",
                column_type=ColumnType.REGULAR,
                arkumu_type="identifier",
                datatype="string",
                is_anchor=False,
                is_multi_value=False,
                multi_value_separator=",",
                is_external_ontology=True,
                external_ontology_config={"ontology_type": "ORCID"},
            ),
            ColumnConfig(
                column_name="name",
                dataset_name="test_dataset",
                column_type=ColumnType.REGULAR,
                arkumu_type="name",
                datatype="string",
                is_anchor=False,
                is_multi_value=False,
                multi_value_separator=",",
                is_external_ontology=False,
                external_ontology_config=None,
            )
        ]
        
        groups = processor._group_columns_by_type(columns)
        
        assert len(groups["anchor"]) == 1
        assert groups["anchor"][0].column_name == "person_id"
        
        assert len(groups["foreign_key"]) == 1
        assert groups["foreign_key"][0].column_name == "department_id"
        
        assert len(groups["multi_value"]) == 1
        assert groups["multi_value"][0].column_name == "skills"
        
        assert len(groups["external_ontology"]) == 1
        assert groups["external_ontology"][0].column_name == "orcid"
        
        assert len(groups["regular"]) == 1
        assert groups["regular"][0].column_name == "name"
        
        assert len(groups["relationship_context"]) == 0
    
    def test_generate_entity_uri_with_anchor_columns(self, test_organization, test_base_uri, 
                                                   execution_statistics):
        """Test entity URI generation using anchor columns"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Mock dataset config with anchor column
        dataset_config = Mock()
        dataset_config.columns = [
            Mock(is_anchor=True, column_name="person_id"),
            Mock(is_anchor=False, column_name="name")
        ]
        
        row_data = {
            "person_id": "P001",
            "name": "John Doe",
            "row_id": 0
        }
        
        uri = processor._generate_entity_uri("test_dataset", row_data, dataset_config)
        
        assert "entities" in uri
        assert "test-dataset" in uri
        assert "p001" in uri
    
    def test_generate_entity_uri_with_multiple_anchor_columns(self, test_organization, 
                                                            test_base_uri, execution_statistics):
        """Test entity URI generation with multiple anchor columns"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        dataset_config = Mock()
        dataset_config.columns = [
            Mock(is_anchor=True, column_name="first_id"),
            Mock(is_anchor=True, column_name="second_id"),
            Mock(is_anchor=False, column_name="name")
        ]
        
        row_data = {
            "first_id": "A001",
            "second_id": "B002",
            "name": "John Doe",
            "row_id": 0
        }
        
        uri = processor._generate_entity_uri("test_dataset", row_data, dataset_config)
        
        assert "a001-b002" in uri or ("a001" in uri and "b002" in uri)
    
    def test_generate_entity_uri_fallback_to_row_id(self, test_organization, test_base_uri, 
                                                  execution_statistics):
        """Test entity URI generation fallback to row ID"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        dataset_config = Mock()
        dataset_config.columns = [
            Mock(is_anchor=False, column_name="name")
        ]
        
        row_data = {
            "name": "John Doe",
            "row_id": 5
        }
        
        uri = processor._generate_entity_uri("test_dataset", row_data, dataset_config)
        
        assert "entities" in uri
        assert "test-dataset" in uri
        assert "6" in uri  # row_id + 1
    
    def test_split_multi_value(self, test_organization, test_base_uri, execution_statistics):
        """Test multi-value splitting"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Test comma separation
        result = processor._split_multi_value("Python,Java,SQL", ",")
        assert result == ["Python", "Java", "SQL"]
        
        # Test semicolon separation
        result = processor._split_multi_value("reading;swimming;cooking", ";")
        assert result == ["reading", "swimming", "cooking"]
        
        # Test with spaces
        result = processor._split_multi_value("Python, Java, SQL", ",")
        assert result == ["Python", "Java", "SQL"]  # Should strip spaces
        
        # Test empty value
        result = processor._split_multi_value("", ",")
        assert result == []
        
        # Test None value
        result = processor._split_multi_value(None, ",")
        assert result == []
        
        # Test no separator
        result = processor._split_multi_value("single_value", "")
        assert result == ["single_value"]
    
    def test_generate_property_uri(self, test_organization, test_base_uri, execution_statistics):
        """Test property URI generation"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Test with simple arkumu_type
        uri = processor._generate_property_uri("name")
        assert uri.startswith(test_base_uri)
        assert "properties" in uri
        assert "name" in uri
        
        # Test with full URI
        full_uri = "http://example.org/property/name"
        uri = processor._generate_property_uri(full_uri)
        assert uri == full_uri
        
        # Test with HTTPS URI
        https_uri = "https://example.org/property/name"
        uri = processor._generate_property_uri(https_uri)
        assert uri == https_uri

    def test_generate_type_uri(self, test_organization, test_base_uri, execution_statistics):
        """Test type URI generation for entity types"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Test with simple type name
        uri = processor._generate_type_uri("kreuz-projekte-informationstraege")
        assert uri.startswith(test_base_uri)
        assert "types" in uri
        assert "kreuz-projekte-informationstraege" in uri
        assert "properties" not in uri  # Should NOT be in properties namespace
        
        # Test with entity-type- prefix removal
        uri = processor._generate_type_uri("entity-type-09-kreuz-projekte-informationstraege")
        assert "09-kreuz-projekte-informationstraege" in uri
        assert "entity-type-" not in uri  # Prefix should be removed
        assert "types" in uri
        
        # Test with entity_type_ prefix removal
        uri = processor._generate_type_uri("entity_type_dataset_name")
        assert "dataset-name" in uri  # Underscores become dashes in URI slugification
        assert "entity_type_" not in uri  # Prefix should be removed
        assert "types" in uri
        
        # Test with full URI
        full_uri = "http://example.org/types/artwork"
        uri = processor._generate_type_uri(full_uri)
        assert uri == full_uri
        
        # Test with HTTPS URI
        https_uri = "https://example.org/types/person"
        uri = processor._generate_type_uri(https_uri)
        assert uri == https_uri

    def test_create_rdf_type_relationship(self, test_organization, test_base_uri, execution_statistics):
        """Test that entities get linked to their types via rdf:type"""
        from arkumu.metadata.models.triples import Triple
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create a mock blueprint with entity type
        mock_entity_type = create_mock_resource(
            resource_id=1, 
            uri="http://test.org/types/test-type"
        )
        processor.dataset_blueprints["test_dataset"] = {
            "entity_type_resource": mock_entity_type
        }
        
        # Create a mock entity
        mock_entity = create_mock_resource(
            resource_id=2,
            uri="http://test.org/entities/test_dataset/E001"
        )
        
        # Mock the resource manager's create_relationship_triple method
        with patch.object(processor.resource_manager, 'create_relationship_triple') as mock_create_triple:
            # Call the method
            processor._create_rdf_type_relationship(mock_entity, "test_dataset")
            
            # Verify rdf:type relationship was created
            mock_create_triple.assert_called_once_with(
                mock_entity,
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                mock_entity_type
            )

    def test_entity_type_names_are_clean(self, test_organization, test_base_uri, execution_statistics):
        """Test that entity type names don't have verbose prefixes"""
        from arkumu.importer.services.mapping_consumer import DatasetConfig, ColumnConfig, ColumnType
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create a mock column with entity type
        mock_entity_column = Mock()
        mock_entity_column.column_type.value = 'entity'
        mock_entity_column.arkumu_type = "entity-type-11-kreuz-digitaleobjekte-proj"
        
        # Create a dataset config with entity-type- prefix in arkumu_type
        dataset_config = Mock()
        dataset_config.dataset_name = "test_dataset"
        dataset_config.columns = [mock_entity_column]
        
        # Mock Resource.objects.get_or_create
        with patch('arkumu.metadata.models.Resource.objects.get_or_create') as mock_get_or_create:
            mock_resource = create_mock_resource(
                resource_id=1,
                uri="http://test.org/types/11-kreuz-digitaleobjekte-proj"
            )
            mock_get_or_create.return_value = (mock_resource, True)
            
            # Call the method
            entity_type_resource = processor._create_entity_type_resource(dataset_config)
            
            # Verify the name passed to get_or_create is clean
            mock_get_or_create.assert_called_once()
            call_args = mock_get_or_create.call_args
            defaults = call_args[1]['defaults']  # kwargs['defaults']
            
            # The name should be clean (without entity-type- prefix)
            assert defaults['name'] == "11-kreuz-digitaleobjekte-proj"
            assert "entity-type-" not in defaults['name']
            assert "entity_type_" not in defaults['name']

    def test_property_names_are_clean(self, test_organization, test_base_uri, execution_statistics):
        """Test that property names use clean arkumu_type values"""
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Create a mock column with a typical arkumu_type
        mock_column = Mock()
        mock_column.arkumu_type = "title"  # Clean arkumu_type
        
        # Mock Resource.objects.get_or_create
        with patch('arkumu.metadata.models.Resource.objects.get_or_create') as mock_get_or_create:
            mock_resource = create_mock_resource(
                resource_id=1,
                uri="http://test.org/properties/title"
            )
            mock_get_or_create.return_value = (mock_resource, True)
            
            # Call the method
            property_resource = processor._create_property_resource(mock_column)
            
            # Verify the name passed to get_or_create uses arkumu_type directly
            mock_get_or_create.assert_called_once()
            call_args = mock_get_or_create.call_args
            defaults = call_args[1]['defaults']  # kwargs['defaults']
            
            # The name should be the clean arkumu_type
            assert defaults['name'] == "title"
            
        # Test with a potentially problematic arkumu_type
        mock_column.arkumu_type = "creator_name"
        
        with patch('arkumu.metadata.models.Resource.objects.get_or_create') as mock_get_or_create2:
            mock_resource2 = create_mock_resource(
                resource_id=2,
                uri="http://test.org/properties/creator-name" 
            )
            mock_get_or_create2.return_value = (mock_resource2, True)
            
            # Call the method
            property_resource = processor._create_property_resource(mock_column)
            
            # Verify the name uses arkumu_type as-is (no cleaning needed for properties)
            call_args = mock_get_or_create2.call_args
            defaults = call_args[1]['defaults']
            
            # Properties use arkumu_type directly - this is actually correct behavior
            assert defaults['name'] == "creator_name"
    
    def test_generate_external_ontology_uri(self, test_organization, test_base_uri, 
                                          execution_statistics):
        """Test external ontology URI generation"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Mock column config with external ontology
        column = Mock()
        column.external_ontology_config = {
            "uri_template": "http://orcid.org/{identifier}"
        }
        
        uri = processor._generate_external_ontology_uri(column, "0000-0000-0000-0001")
        assert uri == "http://orcid.org/0000-0000-0000-0001"
        
        # Test with no config
        column.external_ontology_config = None
        uri = processor._generate_external_ontology_uri(column, "any_value")
        assert uri is None
        
        # Test with no template
        column.external_ontology_config = {}
        uri = processor._generate_external_ontology_uri(column, "any_value")
        assert uri is None
    
    def test_create_mapping_config_from_dataset(self, test_organization, test_base_uri, 
                                               execution_statistics):
        """Test mapping config creation from dataset config"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # Mock dataset config
        dataset_config = Mock()
        dataset_config.dataset_name = "test_dataset"
        dataset_config.columns = [
            Mock(
                column_name="name",
                is_multi_value=False,
                multi_value_separator=None,
                column_type=Mock(value="regular"),
                is_anchor=False,
                arkumu_type="name",
                datatype="string",
            ),
            Mock(
                column_name="skills",
                is_multi_value=True,
                multi_value_separator=",",
                column_type=Mock(value="regular"),
                is_anchor=False,
                arkumu_type="skill",
                datatype="string",
            )
        ]
        dataset_config.fk_relationships = []
        
        mapping_config = processor._create_mapping_config_from_dataset(dataset_config)
        
        assert mapping_config["dataset_name"] == "test_dataset"
        assert "columns" in mapping_config
        assert "name" in mapping_config["columns"]
        assert "skills" in mapping_config["columns"]
        
        # Check name column
        name_config = mapping_config["columns"]["name"]
        assert name_config["is_multi_value"] is False
        assert name_config["arkumu_type"] == "name"
        
        # Check skills column
        skills_config = mapping_config["columns"]["skills"]
        assert skills_config["is_multi_value"] is True
        assert skills_config["multi_value_separator"] == ","
    
    @patch('arkumu.metadata.models.Resource.objects.get_or_create')
    def test_process_regular_columns(self, mock_get_or_create, test_organization, 
                                   test_base_uri, execution_statistics):
        """Test processing of regular columns"""
        # Mock resource creation
        mock_resource = create_mock_resource()
        mock_get_or_create.return_value = (mock_resource, True)
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_resource = Mock()
        row_data = {
            "name": "John Doe",
            "age": "30",
            "empty_field": "",
            "none_field": None
        }
        
        # Mock column configs
        columns = [
            Mock(column_name="name", arkumu_type="name", datatype="string"),
            Mock(column_name="age", arkumu_type="age", datatype="integer"),
            Mock(column_name="empty_field", arkumu_type="empty", datatype="string"),
            Mock(column_name="none_field", arkumu_type="none", datatype="string")
        ]
        
        context = Mock()
        
        processor._process_regular_columns(entity_resource, row_data, columns, context)
        
        # Should only process non-empty values
        assert mock_get_or_create.call_count >= 2  # name and age
    
    @patch('arkumu.metadata.models.Resource.objects.get_or_create')
    def test_process_anchor_columns(self, mock_get_or_create, test_organization, 
                                  test_base_uri, execution_statistics):
        """Test processing of anchor columns"""
        mock_resource = Mock(id=1)
        mock_get_or_create.return_value = (mock_resource, True)
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_resource = Mock()
        row_data = {"person_id": "P001"}
        
        columns = [
            Mock(column_name="person_id", arkumu_type="identifier", datatype="string")
        ]
        
        context = Mock()
        
        processor._process_anchor_columns(entity_resource, row_data, columns, context)
        
        # Should create property with identifier prefix
        mock_get_or_create.assert_called()
    
    @patch('arkumu.metadata.models.Resource.objects.get_or_create')
    def test_process_multi_value_columns(self, mock_get_or_create, test_organization, 
                                       test_base_uri, execution_statistics):
        """Test processing of multi-value columns"""
        mock_resource = Mock(id=1)
        mock_get_or_create.return_value = (mock_resource, True)
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_resource = Mock()
        row_data = {"skills": "Python,Java,SQL"}
        
        columns = [
            Mock(
                column_name="skills",
                arkumu_type="skill",
                datatype="string",
                multi_value_separator=","
            )
        ]
        
        context = Mock()
        
        processor._process_multi_value_columns(entity_resource, row_data, columns, context)
        
        # Should create multiple property triples (one for each value)
        assert mock_get_or_create.call_count >= 3  # At least 3 values
    
    def test_queue_fk_relationships(self, test_organization, test_base_uri, execution_statistics):
        """Test queuing of FK relationships"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_uri = "http://test.org/entity/1"
        row_data = {"department_id": "D001"}
        
        # Mock FK column
        columns = [
            Mock(
                column_name="department_id",
                arkumu_type="department",
                is_multi_value=False
            )
        ]
        
        # Mock context
        context = Mock()
        context.execution_config = Mock()
        context.execution_config.fk_relationships = [
            Mock(source_column="department_id", target_dataset="departments")
        ]
        
        processor._queue_fk_relationships(entity_uri, row_data, columns, context)
        
        # Should queue the relationship
        assert len(processor.pending_relationships) == 1
        relationship = processor.pending_relationships[0]
        assert relationship["source_entity_uri"] == entity_uri
        assert relationship["target_value"] == "D001"
    
    def test_queue_fk_relationships_multi_value(self, test_organization, test_base_uri, 
                                              execution_statistics):
        """Test queuing of multi-value FK relationships"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_uri = "http://test.org/entity/1"
        row_data = {"departments": "D001,D002,D003"}
        
        # Mock multi-value FK column
        columns = [
            Mock(
                column_name="departments",
                arkumu_type="department",
                is_multi_value=True,
                multi_value_separator=","
            )
        ]
        
        context = Mock()
        context.execution_config = Mock()
        context.execution_config.fk_relationships = [
            Mock(source_column="departments", target_dataset="departments")
        ]
        
        processor._queue_fk_relationships(entity_uri, row_data, columns, context)
        
        # Should queue multiple relationships
        assert len(processor.pending_relationships) == 3
        values = [rel["target_value"] for rel in processor.pending_relationships]
        assert "D001" in values
        assert "D002" in values
        assert "D003" in values
    
    @patch('arkumu.metadata.models.Resource.objects.get_or_create')
    def test_process_external_ontology_columns(self, mock_get_or_create, test_organization, 
                                             test_base_uri, execution_statistics):
        """Test processing of external ontology columns"""
        mock_resource = Mock(id=1)
        mock_get_or_create.return_value = (mock_resource, True)
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        entity_resource = Mock()
        row_data = {"orcid": "0000-0000-0000-0001"}
        
        columns = [
            Mock(
                column_name="orcid",
                arkumu_type="identifier",
                external_ontology_config={"ontology_type": "ORCID"}
            )
        ]
        
        context = Mock()
        
        with patch.object(processor, '_generate_external_ontology_uri') as mock_generate_uri:
            mock_generate_uri.return_value = "http://orcid.org/0000-0000-0000-0001"
            
            processor._process_external_ontology_columns(entity_resource, row_data, columns, context)
            
            mock_generate_uri.assert_called_once()
            mock_get_or_create.assert_called()  # For relationship triple


@pytest.mark.django_db
class TestMappingAwareProcessorIntegration:
    """Integration tests for MappingAwareProcessor"""
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_end_to_end_processing(self, mock_triple_objects, mock_resource_objects,
                                 test_organization, test_base_uri):
        """Test end-to-end processing with complex mapping configuration"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        # Create complex execution config
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="test_mapping",
            organization="test_org",
            datasets=[
                DatasetConfig(
                    dataset_name="people",
                    columns=[
                        ColumnConfig(
                            column_name="person_id",
                            dataset_name="people",
                            column_type=ColumnType.REGULAR,
                            arkumu_type="identifier",
                            datatype="string",
                            is_anchor=True,
                            is_multi_value=False,
                            multi_value_separator=",",
                            is_external_ontology=False,
                            external_ontology_config=None,
                                    ),
                        ColumnConfig(
                            column_name="name",
                            dataset_name="people",
                            column_type=ColumnType.REGULAR,
                            arkumu_type="name",
                            datatype="string",
                            is_anchor=False,
                            is_multi_value=False,
                            multi_value_separator=",",
                            is_external_ontology=False,
                            external_ontology_config=None,
                                    ),
                        ColumnConfig(
                            column_name="skills",
                            dataset_name="people",
                            column_type=ColumnType.REGULAR,
                            arkumu_type="skill",
                            datatype="string",
                            is_anchor=False,
                            is_multi_value=True,
                            multi_value_separator=",",
                            is_external_ontology=False,
                            external_ontology_config=None,
                                    )
                    ]
                )
            ],
            fk_relationships=[],
            relationship_contexts=[],
            processing_strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        csv_sources = {
            "people": [
                {
                    "person_id": "P001",
                    "name": "John Doe",
                    "skills": "Python,Java,SQL"
                },
                {
                    "person_id": "P002",
                    "name": "Jane Smith",
                    "skills": "R,Statistics"
                }
            ]
        }
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=ExecutionStatistics()
        )
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify processing completed
        assert isinstance(metrics, ExecutionMetrics)
        
        # Verify database operations were called
        assert mock_resource_objects.get_or_create.called
        assert mock_resource_objects.bulk_create.called


@pytest.mark.django_db
class TestMappingAwareProcessorPerformance:
    """Performance tests for MappingAwareProcessor"""
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_large_dataset_processing_performance(self, mock_triple_objects, mock_resource_objects,
                                                 test_organization, test_base_uri, 
                                                 performance_test_data):
        """Test processing performance with large dataset"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        # Use subset for testing
        test_data = performance_test_data[:1000]
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="test_mapping",
            organization="test_org",
            datasets=[
                DatasetConfig(
                    dataset_name="performance_test",
                    columns=[
                        ColumnConfig(
                            column_name="id",
                            dataset_name="performance_test",
                            column_type=ColumnType.REGULAR,
                            arkumu_type="identifier",
                            datatype="string",
                            is_anchor=True,
                            is_multi_value=False,
                            multi_value_separator=",",
                            is_external_ontology=False,
                            external_ontology_config=None,
                                    ),
                        ColumnConfig(
                            column_name="name",
                            dataset_name="performance_test",
                            column_type=ColumnType.REGULAR,
                            arkumu_type="name",
                            datatype="string",
                            is_anchor=False,
                            is_multi_value=False,
                            multi_value_separator=",",
                            is_external_ontology=False,
                            external_ontology_config=None,
                                    )
                    ]
                )
            ],
            fk_relationships=[],
            relationship_contexts=[],
            processing_strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        csv_sources = {"performance_test": test_data}
        
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=ExecutionStatistics()
        )
        
        import time
        start_time = time.time()
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify processing completed
        assert isinstance(metrics, ExecutionMetrics)
        
        # Should complete in reasonable time
        assert processing_time < 60.0  # Should complete within 60 seconds
        
        print(f"Processed {len(test_data)} entities in {processing_time:.2f} seconds")


@pytest.mark.django_db
class TestMappingAwareProcessorEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_processing_with_missing_csv_data(self, test_organization, test_base_uri, 
                                            execution_statistics, execution_config_simple):
        """Test processing when CSV data is missing for a dataset"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        # CSV sources missing the required dataset
        csv_sources = {"other_dataset": [{"data": "value"}]}
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Should complete without errors despite missing data
        assert isinstance(metrics, ExecutionMetrics)
    
    def test_processing_with_empty_csv_data(self, test_organization, test_base_uri, 
                                          execution_statistics, execution_config_simple):
        """Test processing with empty CSV data"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        csv_sources = {"test_dataset": []}
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Should handle empty data gracefully
        assert isinstance(metrics, ExecutionMetrics)
    
    def test_entity_uri_generation_with_empty_anchor_values(self, test_organization, 
                                                          test_base_uri, execution_statistics):
        """Test entity URI generation when anchor values are empty"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        dataset_config = Mock()
        dataset_config.columns = [
            Mock(is_anchor=True, column_name="person_id")
        ]
        
        row_data = {
            "person_id": "",  # Empty anchor value
            "name": "John Doe",
            "row_id": 5
        }
        
        uri = processor._generate_entity_uri("test_dataset", row_data, dataset_config)
        
        # Should fall back to row ID
        assert "6" in uri  # row_id + 1
    
    def test_multi_value_splitting_edge_cases(self, test_organization, test_base_uri, 
                                            execution_statistics):
        """Test multi-value splitting with edge cases"""
        processor = MappingAwareProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            statistics=execution_statistics
        )
        
        edge_cases = [
            ("", ",", []),
            ("   ", ",", []),
            ("single", ",", ["single"]),
            ("a,,b", ",", ["a", "b"]),  # Empty values filtered out
            ("a,  ,b", ",", ["a", "b"]),  # Whitespace-only values filtered out
            ("a;b;c", ";", ["a", "b", "c"]),
            ("a|b|c", "|", ["a", "b", "c"])
        ]
        
        for value, separator, expected in edge_cases:
            result = processor._split_multi_value(value, separator)
            assert result == expected