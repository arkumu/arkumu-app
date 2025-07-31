"""
Test Complete Schema Blueprint Creation

Tests that complete schema blueprints include ALL relationship types,
not just FK relationships, and can be used for post-import CRUD.
"""

import pytest
import logging
from unittest.mock import patch, MagicMock
from datetime import datetime

from django.core.cache import cache

from arkumu.importer.services.execution.complete_schema_processor import CompleteSchemaProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.config_translator import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType
)
from arkumu.metadata.services.mapping.processing_plan import FKConfig
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)


@pytest.mark.django_db(transaction=True)
class TestCompleteSchemaBlueprints:
    """Test complete schema blueprint creation with all relationship types"""
    
    @pytest.fixture
    def mock_execution_config(self):
        """Create a mock execution config with all relationship types"""
        # Author dataset with multi-value skills and external ORCID
        author_columns = [
            ColumnConfig(
                column_name="author_id",
                dataset_name="authors",
                column_type=ColumnType.ANCHOR,
                arkumu_type="author_identifier"
            ),
            ColumnConfig(
                column_name="name",
                dataset_name="authors",
                column_type=ColumnType.REGULAR,
                arkumu_type="person_name"
            ),
            ColumnConfig(
                column_name="skills",
                dataset_name="authors",
                column_type=ColumnType.MULTI_VALUE,
                arkumu_type="skill"
            ),
            ColumnConfig(
                column_name="orcid",
                dataset_name="authors",
                column_type=ColumnType.EXTERNAL_ONTOLOGY,
                arkumu_type="orcid_identifier"
            )
        ]
        
        # Add attributes that aren't in constructor
        author_columns[2].separator = ","
        author_columns[3].ontology_type = "orcid"
        author_columns[3].uri_template = "https://orcid.org/{value}"
        
        # Book dataset
        book_columns = [
            ColumnConfig(
                column_name="book_id",
                dataset_name="books",
                column_type=ColumnType.ANCHOR,
                arkumu_type="book_identifier"
            ),
            ColumnConfig(
                column_name="title",
                dataset_name="books",
                column_type=ColumnType.REGULAR,
                arkumu_type="book_title"
            ),
            ColumnConfig(
                column_name="genres",
                dataset_name="books",
                column_type=ColumnType.MULTI_VALUE,
                arkumu_type="book_genre"
            )
        ]
        
        # Add multi-value separator
        book_columns[2].separator = "|"
        
        # Authorship junction table  
        authorship_columns = [
            ColumnConfig(
                column_name="author_id",
                dataset_name="authorships",
                column_type=ColumnType.FOREIGN_KEY,
                arkumu_type="author_reference"
            ),
            ColumnConfig(
                column_name="book_id",
                dataset_name="authorships", 
                column_type=ColumnType.FOREIGN_KEY,
                arkumu_type="book_reference"
            ),
            ColumnConfig(
                column_name="role",
                dataset_name="authorships",
                column_type=ColumnType.REGULAR,
                arkumu_type="authorship_role"
            ),
            ColumnConfig(
                column_name="contribution_percent",
                dataset_name="authorships",
                column_type=ColumnType.REGULAR,
                arkumu_type="contribution_level"
            )
        ]
        
        # Add fk_config attribute separately to avoid constructor issues
        authorship_columns[0].fk_config = FKConfig(
            source_dataset="authorships",
            source_column="author_id", 
            target_dataset="authors",
            target_column="author_id"
        )
        authorship_columns[1].fk_config = FKConfig(
            source_dataset="authorships",
            source_column="book_id",
            target_dataset="books", 
            target_column="book_id"
        )
        
        # Create datasets
        datasets = [
            DatasetConfig(
                dataset_name="authors",
                columns=author_columns
            ),
            DatasetConfig(
                dataset_name="books",
                columns=book_columns
            ),
            DatasetConfig(
                dataset_name="authorships",
                columns=authorship_columns
            )
        ]
        
        # Create relationship context for junction table
        relationship_context = MagicMock()
        relationship_context.dataset_name = "authorships"
        relationship_context.context_type = "junction"
        relationship_context.primary_fk = "author_id"
        relationship_context.secondary_fk = "book_id"
        relationship_context.primary_dataset = "authors"
        relationship_context.secondary_dataset = "books"
        relationship_context.context_columns = ["role", "contribution_percent"]
        
        # Create execution config
        config = ExecutionConfig(
            mapping_id=123,
            mapping_name="Test Complete Schema Mapping",
            organization="TEST_ORG",
            datasets=datasets
        )
        config.relationship_contexts = [relationship_context]
        
        return config
    
    def test_complete_schema_includes_all_relationship_types(self, mock_execution_config):
        """Test that complete schema includes all 5 relationship types"""
        
        # Clear any cached blueprints
        cache.clear()
        
        # Create processor
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-complete.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        # Create complete schema blueprints
        processor._create_complete_schema_blueprints(mock_execution_config)
        
        # Verify all datasets have blueprints
        assert len(processor.dataset_blueprints) == 3
        assert "authors" in processor.dataset_blueprints
        assert "books" in processor.dataset_blueprints
        assert "authorships" in processor.dataset_blueprints
        
        # Check AUTHORS blueprint has complete schema
        authors_bp = processor.dataset_blueprints["authors"]
        
        # Basic schema elements (from parent)
        assert 'dataset_resource' in authors_bp
        assert 'entity_type_resource' in authors_bp
        assert 'property_resources' in authors_bp
        assert len(authors_bp['property_resources']) == 4  # All columns
        
        # Extended schema elements (new)
        assert 'column_metadata' in authors_bp
        assert 'multi_value_schemas' in authors_bp
        assert 'external_ontology_schemas' in authors_bp
        assert 'anchor_columns' in authors_bp
        
        # Verify multi-value schema
        assert 'skills' in authors_bp['multi_value_schemas']
        skills_schema = authors_bp['multi_value_schemas']['skills']
        assert skills_schema['separator'] == ','
        assert skills_schema['creates_multiple_triples'] is True
        
        # Verify external ontology schema
        assert 'orcid' in authors_bp['external_ontology_schemas']
        orcid_schema = authors_bp['external_ontology_schemas']['orcid']
        assert orcid_schema['ontology_type'] == 'orcid'
        assert orcid_schema['uri_template'] == 'https://orcid.org/{value}'
        
        # Verify anchor columns
        assert len(authors_bp['anchor_columns']) == 1
        assert authors_bp['anchor_columns'][0]['column_name'] == 'author_id'
        
        # Check AUTHORSHIPS blueprint has junction schema
        authorships_bp = processor.dataset_blueprints["authorships"]
        assert 'junction_schema' in authorships_bp
        
        junction_schema = authorships_bp['junction_schema']
        assert junction_schema['primary_fk'] == 'author_id'
        assert junction_schema['secondary_fk'] == 'book_id'
        assert junction_schema['primary_dataset'] == 'authors'
        assert junction_schema['secondary_dataset'] == 'books'
        assert 'role' in junction_schema['context_columns']
        assert 'contribution_percent' in junction_schema['context_columns']
        
        logger.info("✅ Complete schema includes all relationship types")
    
    def test_complete_schema_caching(self, mock_execution_config):
        """Test that complete schemas are properly cached"""
        
        # Clear cache
        cache.clear()
        
        # Create processor
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-cache.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        # First call - should create and cache
        with patch.object(processor, '_extend_blueprints_with_complete_schema') as mock_extend:
            processor._create_complete_schema_blueprints(mock_execution_config)
            assert mock_extend.called
        
        # Verify cache was set
        cache_key = f"complete_schema_blueprints_mapping_{mock_execution_config.mapping_id}"
        cached_blueprints = cache.get(cache_key)
        assert cached_blueprints is not None
        assert len(cached_blueprints) == 3
        
        # Second call - should use cache
        processor2 = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-cache.arkumu.org/data", 
            statistics=ExecutionStatistics()
        )
        
        with patch.object(processor2, '_extend_blueprints_with_complete_schema') as mock_extend2:
            processor2._create_complete_schema_blueprints(mock_execution_config)
            assert not mock_extend2.called  # Should not be called due to cache hit
        
        # Verify same blueprints loaded
        assert processor2.dataset_blueprints == cached_blueprints
        
        logger.info("✅ Complete schema caching works correctly")
    
    def test_schema_for_entity_creation(self, mock_execution_config):
        """Test getting schema for post-import entity creation"""
        
        # Create processor with complete schema
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-crud.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        processor._create_complete_schema_blueprints(mock_execution_config)
        
        # Get schema for entity creation
        author_schema = processor.get_schema_for_entity_creation("authors")
        
        assert author_schema is not None
        assert author_schema['dataset_name'] == 'authors'
        assert 'entity_type' in author_schema
        assert 'properties' in author_schema
        assert 'column_metadata' in author_schema
        assert 'multi_value_schemas' in author_schema
        assert 'external_ontology_schemas' in author_schema
        assert 'anchor_columns' in author_schema
        
        # Verify schema contains all needed info
        assert len(author_schema['properties']) == 4
        assert 'skills' in author_schema['multi_value_schemas']
        assert 'orcid' in author_schema['external_ontology_schemas']
        assert len(author_schema['anchor_columns']) == 1
        
        logger.info("✅ Schema for entity creation contains complete information")
    
    def test_create_entity_from_complete_schema(self, mock_execution_config):
        """Test creating new entity using complete schema"""
        
        # Create processor with complete schema
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-create.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        processor._create_complete_schema_blueprints(mock_execution_config)
        
        # Create new author entity
        author_data = {
            'author_id': 'A123',
            'name': 'Jane Doe',
            'skills': 'Python,JavaScript,SQL',
            'orcid': '0000-0002-1825-0097'
        }
        
        # Mock resource manager methods
        processor.resource_manager.create_entity_resource = MagicMock(
            return_value=Resource(uri="http://test-create.arkumu.org/data/authors/A123")
        )
        processor.resource_manager.create_relationship_triple = MagicMock()
        processor.resource_manager.create_property_triple = MagicMock()
        
        # Create entity
        entity = processor.create_entity_from_schema("authors", author_data)
        
        assert entity is not None
        assert entity.uri == "http://test-create.arkumu.org/data/authors/A123"
        
        # Verify multi-value property created multiple triples
        property_calls = processor.resource_manager.create_property_triple.call_args_list
        skill_calls = [call for call in property_calls if 'Python' in str(call) or 'JavaScript' in str(call) or 'SQL' in str(call)]
        assert len(skill_calls) == 3  # One for each skill
        
        # Verify external ontology created relationship
        relationship_calls = processor.resource_manager.create_relationship_triple.call_args_list
        orcid_calls = [call for call in relationship_calls if 'orcid.org' in str(call)]
        assert len(orcid_calls) >= 1
        
        logger.info("✅ Entity creation uses complete schema correctly")
    
    def test_column_metadata_completeness(self, mock_execution_config):
        """Test that column metadata captures all column information"""
        
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-meta.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        processor._create_complete_schema_blueprints(mock_execution_config)
        
        # Check authors column metadata
        authors_bp = processor.dataset_blueprints["authors"]
        col_metadata = authors_bp['column_metadata']
        
        # Check anchor column metadata
        assert 'author_id' in col_metadata
        author_id_meta = col_metadata['author_id']
        assert author_id_meta['is_anchor'] is True
        assert author_id_meta['column_type'] == 'anchor'
        
        # Check multi-value column metadata
        assert 'skills' in col_metadata
        skills_meta = col_metadata['skills']
        assert skills_meta['is_multi_value'] is True
        assert skills_meta['multi_value_separator'] == ','
        
        # Check external ontology metadata
        assert 'orcid' in col_metadata
        orcid_meta = col_metadata['orcid']
        assert orcid_meta['is_external_ontology'] is True
        assert orcid_meta['ontology_type'] == 'orcid'
        assert orcid_meta['uri_template'] == 'https://orcid.org/{value}'
        
        # Check FK column metadata in authorships
        authorships_bp = processor.dataset_blueprints["authorships"]
        auth_col_metadata = authorships_bp['column_metadata']
        
        assert 'author_id' in auth_col_metadata
        assert auth_col_metadata['author_id']['has_fk'] is True
        assert auth_col_metadata['author_id']['column_type'] == 'foreign_key'
        
        logger.info("✅ Column metadata captures all column types correctly")
    
    def test_schema_statistics_logging(self, mock_execution_config):
        """Test that complete schema statistics are logged correctly"""
        
        processor = CompleteSchemaProcessor(
            organization=mock_execution_config.organization,
            base_uri="http://test-stats.arkumu.org/data",
            statistics=ExecutionStatistics()
        )
        
        # Capture log output
        with patch.object(logger, 'info') as mock_log:
            processor._create_complete_schema_blueprints(mock_execution_config)
            
            # Find statistics log calls
            log_calls = [str(call) for call in mock_log.call_args_list]
            stats_logs = [call for call in log_calls if 'Complete Schema Statistics' in call]
            
            assert len(stats_logs) > 0
            
            # Verify statistics include new counts
            all_logs = '\n'.join(log_calls)
            assert 'Multi-value Columns: 2' in all_logs  # skills + genres
            assert 'External Ontologies: 1' in all_logs  # orcid
            assert 'Junction Tables: 1' in all_logs      # authorships
        
        logger.info("✅ Complete schema statistics logged correctly")