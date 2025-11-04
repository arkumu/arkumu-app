"""
Tests for config translator service.

Tests the ConfigTranslator class which converts GUI mapping configurations
to execution engine format.
"""

import pytest
from copy import deepcopy
from unittest.mock import Mock, patch
from datetime import datetime

from arkumu.importer.services.mapping_consumer.config_translator import (
    ConfigTranslator, ExecutionConfig, DatasetConfig, ColumnConfig, 
    FKRelationship, RelationshipContext, ExternalOntology, ExecutionPhase,
    ColumnType, ProcessingStrategy
)


class TestConfigTranslator:
    """Test suite for ConfigTranslator class"""

    @pytest.fixture
    def config_translator(self):
        """Create a ConfigTranslator instance"""
        return ConfigTranslator()

    @pytest.fixture
    def sample_gui_config(self):
        """Sample GUI mapping configuration"""
        return {
            'version': '1.1',
            '_metadata': {
                'mapping_id': 1,
                'mapping_name': 'Test Mapping',
                'organization': 'TEST_ORG',
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'created_by': 'testuser'
            },
            'workspace_columns': {
                'people': {
                    'name': {
                        'arkumu_type': 'Person.name',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                        'is_anchor': True,
                        'is_multi_value': False,
                        'multi_value_separator': ',',
                        'confidence': 0.95,
                        'is_external_ontology': False
                    },
                    'tags': {
                        'arkumu_type': 'Person.tags',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                        'is_anchor': False,
                        'is_multi_value': True,
                        'multi_value_separator': '|',
                        'confidence': 0.80,
                        'is_external_ontology': False
                    },
                    'orcid_id': {
                        'arkumu_type': 'Person.orcid',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                        'is_anchor': False,
                        'is_multi_value': False,
                        'confidence': 0.90,
                        'is_external_ontology': True,
                        'external_ontology': {
                            'ontology_type': 'orcid',
                            'uri_template': 'https://orcid.org/{identifier}'
                        }
                    }
                },
                'locations': {
                    'city': {
                        'arkumu_type': 'Location.city',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                        'is_anchor': True,
                        'is_multi_value': False,
                        'confidence': 0.85,
                        'is_external_ontology': False
                    },
                    'country': {
                        'arkumu_type': 'Location.country',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                        'is_anchor': False,
                        'is_multi_value': False,
                        'confidence': 0.90,
                        'is_external_ontology': False
                    }
                }
            },
            'selected_datasets': ['people', 'locations'],
            'fk_relationships': {
                'fk_1': {
                    'source_column': 'location_id',
                    'source_dataset': 'people',
                    'target_column': 'id',
                    'target_dataset': 'locations',
                    'relationship_type': 'resides_in',
                    'direction': 'outgoing',
                    'is_multi_value': False,
                    'multi_value_separator': ',',
                    'confidence': 0.80
                },
                'fk_2': {
                    'source_column': 'location_codes',
                    'source_dataset': 'people',
                    'target_column': 'code',
                    'target_dataset': 'locations',
                    'relationship_type': 'associated_with',
                    'direction': 'outgoing',
                    'is_multi_value': True,
                    'multi_value_separator': ';',
                    'confidence': 0.70
                }
            },
            'relationship_contexts': {
                'context_1': {
                    'primary_fk': 'fk_1',
                    'secondary_fk': 'fk_2',
                    'context_columns': ['start_date', 'end_date'],
                    'context_type': 'temporal',
                    'dataset_name': 'people'
                }
            },
            'external_ontologies': {
                'orcid_1': {
                    'column_name': 'orcid_id',
                    'dataset_name': 'people',
                    'ontology_type': 'orcid',
                    'uri_template': 'https://orcid.org/{identifier}',
                    'identifier_column': 'orcid_id',
                    'validation_enabled': True
                }
            },
            'import_strategy': {
                'update_strategy': 'UPDATE_VALUES',
                'bulk_size': 2000,
                'multi_value_threshold': 0.3,
                'enable_progress_tracking': True,
                'batch_processing': True,
                'processing_strategy': 'streaming_entity_centric'
            }
        }

    def test_translate_mapping_config_basic(self, config_translator, sample_gui_config):
        """Test basic translation of mapping configuration"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        assert isinstance(execution_config, ExecutionConfig)
        assert execution_config.mapping_id == 1
        assert execution_config.mapping_name == 'Test Mapping'
        assert execution_config.organization == 'TEST_ORG'
        assert execution_config.version == '1.1'
        assert execution_config.processing_strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC

    def test_translate_workspace_columns(self, config_translator, sample_gui_config):
        """Test translation of workspace columns"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        # Check column configurations
        assert len(execution_config.column_configurations) == 5
        
        # Check specific column configurations
        name_config = execution_config.column_configurations['people.name']
        assert name_config.column_name == 'name'
        assert name_config.dataset_name == 'people'
        assert name_config.arkumu_type == 'Person.name'
        assert name_config.is_anchor is True
        assert name_config.column_type == ColumnType.ANCHOR
        assert name_config.confidence == 0.95

        tags_config = execution_config.column_configurations['people.tags']
        assert tags_config.is_multi_value is True
        assert tags_config.multi_value_separator == '|'
        assert tags_config.column_type == ColumnType.MULTI_VALUE

        orcid_config = execution_config.column_configurations['people.orcid_id']
        assert orcid_config.is_external_ontology is True
        assert orcid_config.column_type == ColumnType.EXTERNAL_ONTOLOGY
        assert orcid_config.external_ontology_config is not None

    def test_translate_fk_relationships(self, config_translator, sample_gui_config):
        """Test translation of FK relationships"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        assert len(execution_config.fk_relationships) == 2
        
        # Check first FK relationship
        fk_1 = execution_config.fk_relationships[0]
        assert fk_1.source_column == 'location_id'
        assert fk_1.source_dataset == 'people'
        assert fk_1.target_column == 'id'
        assert fk_1.target_dataset == 'locations'
        assert fk_1.relationship_type == 'resides_in'
        assert fk_1.direction == 'outgoing'
        assert fk_1.is_multi_value is False
        assert fk_1.confidence == 0.80

        # Check second FK relationship (multi-value)
        fk_2 = execution_config.fk_relationships[1]
        assert fk_2.source_column == 'location_codes'
        assert fk_2.is_multi_value is True
        assert fk_2.multi_value_separator == ';'
        assert fk_2.confidence == 0.70

    def test_translate_relationship_contexts(self, config_translator, sample_gui_config):
        """Test translation of relationship contexts"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        assert len(execution_config.relationship_contexts) == 1
        
        context = execution_config.relationship_contexts[0]
        assert context.context_id == 'context_1'
        assert context.primary_fk == 'fk_1'
        assert context.secondary_fk == 'fk_2'
        assert context.context_columns == ['start_date', 'end_date']
        assert context.context_type == 'temporal'
        assert context.dataset_name == 'people'

    def test_translate_external_ontologies(self, config_translator, sample_gui_config):
        """Test translation of external ontologies"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        assert len(execution_config.external_ontologies) == 1
        
        ontology = execution_config.external_ontologies[0]
        assert ontology.column_name == 'orcid_id'
        assert ontology.dataset_name == 'people'
        assert ontology.ontology_type == 'orcid'
        assert ontology.uri_template == 'https://orcid.org/{identifier}'
        assert ontology.identifier_column == 'orcid_id'
        assert ontology.validation_enabled is True

    def test_translate_external_ontologies_list_support(self, config_translator, sample_gui_config):
        """Columns using the new external_ontologies list are normalised correctly."""
        config = deepcopy(sample_gui_config)
        column = config['workspace_columns']['people']['orcid_id']
        column.pop('external_ontology', None)
        column['external_ontologies'] = [
            {
                'ontology_type': 'wikidata',
                'uri_template': 'https://www.wikidata.org/entity/{identifier}',
                'identifier_column': 'wikidata_id',
                'validation_enabled': True,
            },
            {
                'ontology_type': 'gnd',
                'uri_template': 'https://d-nb.info/gnd/{identifier}',
                'identifier_column': 'gnd_id',
                'validation_enabled': False,
            },
        ]
        config['external_ontologies'] = {}

        execution_config = config_translator.translate_mapping_config(config)
        orcid_config = execution_config.column_configurations['people.orcid_id']

        assert orcid_config.is_external_ontology is True
        assert len(orcid_config.external_ontology_configs) == 2
        assert orcid_config.external_ontology_config == orcid_config.external_ontology_configs[0]

        assert len(execution_config.external_ontologies) == 2
        assert execution_config.external_ontologies[0].ontology_type == 'wikidata'
        assert execution_config.external_ontologies[0].uri_template == 'https://www.wikidata.org/entity/{identifier}'
        assert execution_config.external_ontologies[1].ontology_type == 'gnd'
        assert execution_config.external_ontologies[1].uri_template == 'https://d-nb.info/gnd/{identifier}'

    def test_external_ontology_without_template_is_skipped(self, config_translator, sample_gui_config):
        """External ontology entries without a template are ignored during translation."""
        config = deepcopy(sample_gui_config)
        column = config['workspace_columns']['people']['orcid_id']
        column.pop('external_ontology', None)
        column['external_ontologies'] = [
            {
                'ontology_type': 'wikidata',
                'uri_template': '',
                'identifier_column': 'wikidata_id',
                'validation_enabled': True,
            }
        ]
        config['external_ontologies'] = {}

        execution_config = config_translator.translate_mapping_config(config)
        orcid_config = execution_config.column_configurations['people.orcid_id']

        assert orcid_config.is_external_ontology is True
        assert len(orcid_config.external_ontology_configs) == 1
        assert orcid_config.external_ontology_config == orcid_config.external_ontology_configs[0]
        assert execution_config.external_ontologies == []

    def test_translate_import_strategy(self, config_translator, sample_gui_config):
        """Test translation of import strategy"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        strategy = execution_config.import_strategy
        assert strategy['update_strategy'] == 'UPDATE_VALUES'
        assert strategy['bulk_size'] == 2000
        assert strategy['multi_value_threshold'] == 0.3
        assert strategy['enable_progress_tracking'] is True
        assert strategy['batch_processing'] is True
        
        assert execution_config.processing_strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC

    def test_translate_import_strategy_invalid_processing_strategy(self, config_translator, sample_gui_config):
        """Test translation with invalid processing strategy"""
        sample_gui_config['import_strategy']['processing_strategy'] = 'invalid_strategy'
        
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        # Should default to AUTO for invalid strategy
        assert execution_config.processing_strategy == ProcessingStrategy.AUTO

    def test_build_dataset_configurations(self, config_translator, sample_gui_config):
        """Test building dataset configurations"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        assert len(execution_config.datasets) == 2
        
        # Check people dataset
        people_dataset = execution_config.get_dataset_config('people')
        assert people_dataset is not None
        assert people_dataset.dataset_name == 'people'
        assert len(people_dataset.columns) == 3
        assert people_dataset.primary_key_columns == ['name']  # Anchor column
        assert 'locations' in people_dataset.dependencies  # FK to locations

        # Check locations dataset
        locations_dataset = execution_config.get_dataset_config('locations')
        assert locations_dataset is not None
        assert locations_dataset.dataset_name == 'locations'
        assert len(locations_dataset.columns) == 2
        assert locations_dataset.primary_key_columns == ['city']  # Anchor column
        assert len(locations_dataset.dependencies) == 0  # No dependencies

    def test_skipped_datasets(self, config_translator, sample_gui_config):
        """Test that unselected datasets are skipped"""
        # Add dataset to workspace_columns but not to selected_datasets
        sample_gui_config['workspace_columns']['organizations'] = {
            'name': {
                'arkumu_type': 'Organization.name',
                'datatype': 'http://www.w3.org/2001/XMLSchema#string',
                'is_anchor': True
            }
        }
        
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        # Should not create config for unselected dataset
        assert execution_config.get_dataset_config('organizations') is None
        assert 'organizations.name' not in execution_config.column_configurations

    def test_get_execution_summary(self, config_translator, sample_gui_config):
        """Test generation of execution summary"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        summary = config_translator.get_execution_summary(execution_config)
        
        assert 'mapping_info' in summary
        assert 'datasets' in summary
        assert 'columns' in summary
        assert 'relationships' in summary
        assert 'processing' in summary
        
        # Check mapping info
        mapping_info = summary['mapping_info']
        assert mapping_info['id'] == 1
        assert mapping_info['name'] == 'Test Mapping'
        assert mapping_info['organization'] == 'TEST_ORG'
        assert mapping_info['version'] == '1.1'
        
        # Check datasets
        datasets = summary['datasets']
        assert datasets['count'] == 2
        assert 'people' in datasets['names']
        assert 'locations' in datasets['names']
        assert datasets['with_dependencies'] == 1  # Only people has dependencies
        
        # Check columns
        columns = summary['columns']
        assert columns['total'] == 5
        assert columns['anchor_columns'] == 2
        assert columns['multi_value_columns'] == 1
        assert 'anchor' in columns['types']
        assert 'multi_value' in columns['types']
        assert 'external_ontology' in columns['types']
        
        # Check relationships
        relationships = summary['relationships']
        assert relationships['fk_relationships'] == 2
        assert relationships['relationship_contexts'] == 1
        assert relationships['external_ontologies'] == 1
        
        # Check processing
        processing = summary['processing']
        assert processing['strategy'] == 'streaming_entity_centric'
        assert processing['estimated_complexity'] == 'medium'

    def test_execution_config_helper_methods(self, config_translator, sample_gui_config):
        """Test ExecutionConfig helper methods"""
        execution_config = config_translator.translate_mapping_config(sample_gui_config)
        
        # Test get_dataset_config
        people_dataset = execution_config.get_dataset_config('people')
        assert people_dataset is not None
        assert people_dataset.dataset_name == 'people'
        
        nonexistent_dataset = execution_config.get_dataset_config('nonexistent')
        assert nonexistent_dataset is None
        
        # Test get_column_config
        name_column = execution_config.get_column_config('people', 'name')
        assert name_column is not None
        assert name_column.column_name == 'name'
        assert name_column.dataset_name == 'people'
        
        nonexistent_column = execution_config.get_column_config('people', 'nonexistent')
        assert nonexistent_column is None
        
        # Test get_fk_relationships_for_dataset
        people_fks = execution_config.get_fk_relationships_for_dataset('people')
        assert len(people_fks) == 2  # Both FKs have people as source
        
        locations_fks = execution_config.get_fk_relationships_for_dataset('locations')
        assert len(locations_fks) == 2  # Both FKs have locations as target
        
        nonexistent_fks = execution_config.get_fk_relationships_for_dataset('nonexistent')
        assert len(nonexistent_fks) == 0

    def test_minimal_configuration(self, config_translator):
        """Test translation with minimal configuration"""
        minimal_config = {
            'version': '1.0',
            '_metadata': {
                'mapping_id': 2,
                'mapping_name': 'Minimal Mapping',
                'organization': 'MIN_ORG'
            },
            'workspace_columns': {
                'simple': {
                    'name': {
                        'arkumu_type': 'Entity.name',
                        'datatype': 'http://www.w3.org/2001/XMLSchema#string'
                    }
                }
            },
            'selected_datasets': ['simple'],
            'fk_relationships': {},
            'relationship_contexts': {},
            'external_ontologies': {},
            'import_strategy': {}
        }
        
        execution_config = config_translator.translate_mapping_config(minimal_config)
        
        assert execution_config.mapping_id == 2
        assert execution_config.mapping_name == 'Minimal Mapping'
        assert execution_config.organization == 'MIN_ORG'
        assert execution_config.version == '1.0'
        assert len(execution_config.datasets) == 1
        assert len(execution_config.column_configurations) == 1
        assert len(execution_config.fk_relationships) == 0
        assert len(execution_config.relationship_contexts) == 0
        assert len(execution_config.external_ontologies) == 0
        
        # Check default import strategy values
        strategy = execution_config.import_strategy
        assert strategy['update_strategy'] == 'SKIP_EXISTING'
        assert strategy['bulk_size'] == 1000
        assert strategy['multi_value_threshold'] == 0.2
        assert strategy['enable_progress_tracking'] is True
        assert strategy['batch_processing'] is True

    def test_column_type_determination(self, config_translator):
        """Test correct column type determination"""
        config = {
            'version': '1.1',
            '_metadata': {'mapping_id': 1, 'mapping_name': 'Test', 'organization': 'TEST'},
            'workspace_columns': {
                'dataset': {
                    'anchor_col': {'arkumu_type': 'Entity.id', 'is_anchor': True},
                    'multi_col': {'arkumu_type': 'Entity.tags', 'is_multi_value': True},
                    'external_col': {'arkumu_type': 'Entity.orcid', 'is_external_ontology': True},
                    'regular_col': {'arkumu_type': 'Entity.name'}
                }
            },
            'selected_datasets': ['dataset'],
            'fk_relationships': {
                'fk1': {
                    'source_column': 'fk_col',
                    'source_dataset': 'dataset',
                    'target_column': 'id',
                    'target_dataset': 'other',
                    'relationship_type': 'relates_to'
                }
            },
            'relationship_contexts': {},
            'external_ontologies': {},
            'import_strategy': {}
        }
        
        # Add the FK column to workspace columns
        config['workspace_columns']['dataset']['fk_col'] = {
            'arkumu_type': 'Entity.fk',
            'is_anchor': False
        }
        
        execution_config = config_translator.translate_mapping_config(config)
        
        # Check column types
        assert execution_config.column_configurations['dataset.anchor_col'].column_type == ColumnType.ANCHOR
        assert execution_config.column_configurations['dataset.multi_col'].column_type == ColumnType.MULTI_VALUE
        assert execution_config.column_configurations['dataset.external_col'].column_type == ColumnType.EXTERNAL_ONTOLOGY
        assert execution_config.column_configurations['dataset.regular_col'].column_type == ColumnType.REGULAR
        assert execution_config.column_configurations['dataset.fk_col'].column_type == ColumnType.FOREIGN_KEY
        
    def test_relationship_context_column_detection(self, config_translator):
        """Test that columns with is_relationship_context=True are correctly detected"""
        config = {
            'version': '1.1',
            '_metadata': {'mapping_id': 1, 'mapping_name': 'Test', 'organization': 'TEST'},
            'workspace_columns': {
                'junction_table': {
                    'context_col': {
                        'arkumu_type': 'Entity.value',
                        'is_relationship_context': True,
                        'relationship_context': {
                            'context_predicate': 'hasValue',
                            'primary_fk_column': 'entity1_id',
                            'secondary_fk_column': 'entity2_id'
                        }
                    },
                    'regular_col': {
                        'arkumu_type': 'Entity.name',
                        'is_relationship_context': False
                    }
                }
            },
            'selected_datasets': ['junction_table'],
            'fk_relationships': {},
            'relationship_contexts': {},
            'external_ontologies': {},
            'import_strategy': {}
        }
        
        execution_config = config_translator.translate_mapping_config(config)
        
        # Check that relationship context column is correctly detected
        assert execution_config.column_configurations['junction_table.context_col'].column_type == ColumnType.RELATIONSHIP_CONTEXT
        assert execution_config.column_configurations['junction_table.regular_col'].column_type == ColumnType.REGULAR


class TestDataClasses:
    """Test the data classes used in config translation"""

    def test_column_config_creation(self):
        """Test ColumnConfig creation"""
        config = ColumnConfig(
            column_name='test_col',
            dataset_name='test_dataset',
            arkumu_type='Entity.test',
            datatype='http://www.w3.org/2001/XMLSchema#string',
            is_anchor=True,
            is_multi_value=False,
            confidence=0.95
        )
        
        assert config.column_name == 'test_col'
        assert config.dataset_name == 'test_dataset'
        assert config.arkumu_type == 'Entity.test'
        assert config.is_anchor is True
        assert config.confidence == 0.95
        assert config.column_type == ColumnType.REGULAR  # Default

    def test_fk_relationship_creation(self):
        """Test FKRelationship creation"""
        fk = FKRelationship(
            source_column='source_col',
            source_dataset='source_dataset',
            target_column='target_col',
            target_dataset='target_dataset',
            relationship_type='relates_to',
            direction='outgoing',
            is_multi_value=True,
            multi_value_separator=';',
            confidence=0.80
        )
        
        assert fk.source_column == 'source_col'
        assert fk.source_dataset == 'source_dataset'
        assert fk.target_column == 'target_col'
        assert fk.target_dataset == 'target_dataset'
        assert fk.relationship_type == 'relates_to'
        assert fk.direction == 'outgoing'
        assert fk.is_multi_value is True
        assert fk.multi_value_separator == ';'
        assert fk.confidence == 0.80

    def test_relationship_context_creation(self):
        """Test RelationshipContext creation"""
        context = RelationshipContext(
            context_id='ctx_1',
            primary_fk='fk_1',
            secondary_fk='fk_2',
            context_columns=['start_date', 'end_date'],
            context_type='temporal',
            dataset_name='junction_dataset'
        )
        
        assert context.context_id == 'ctx_1'
        assert context.primary_fk == 'fk_1'
        assert context.secondary_fk == 'fk_2'
        assert context.context_columns == ['start_date', 'end_date']
        assert context.context_type == 'temporal'
        assert context.dataset_name == 'junction_dataset'

    def test_external_ontology_creation(self):
        """Test ExternalOntology creation"""
        ontology = ExternalOntology(
            column_name='orcid_id',
            dataset_name='people',
            ontology_type='orcid',
            uri_template='https://orcid.org/{identifier}',
            identifier_column='orcid_id',
            validation_enabled=True
        )
        
        assert ontology.column_name == 'orcid_id'
        assert ontology.dataset_name == 'people'
        assert ontology.ontology_type == 'orcid'
        assert ontology.uri_template == 'https://orcid.org/{identifier}'
        assert ontology.identifier_column == 'orcid_id'
        assert ontology.validation_enabled is True

    def test_dataset_config_creation(self):
        """Test DatasetConfig creation"""
        columns = [
            ColumnConfig('col1', 'dataset1', 'Entity.col1', is_anchor=True),
            ColumnConfig('col2', 'dataset1', 'Entity.col2')
        ]
        
        dataset = DatasetConfig(
            dataset_name='dataset1',
            columns=columns,
            primary_key_columns=['col1'],
            dependencies=['dataset2']
        )
        
        assert dataset.dataset_name == 'dataset1'
        assert len(dataset.columns) == 2
        assert dataset.primary_key_columns == ['col1']
        assert dataset.dependencies == ['dataset2']

    def test_execution_config_creation(self):
        """Test ExecutionConfig creation with defaults"""
        config = ExecutionConfig(
            mapping_id=1,
            mapping_name='Test Mapping',
            organization='TEST_ORG'
        )
        
        assert config.mapping_id == 1
        assert config.mapping_name == 'Test Mapping'
        assert config.organization == 'TEST_ORG'
        assert config.version == '1.1'
        assert config.processing_strategy == ProcessingStrategy.AUTO
        assert config.estimated_complexity == 'medium'
        assert len(config.datasets) == 0
        assert len(config.column_configurations) == 0
        assert len(config.fk_relationships) == 0


class TestEnums:
    """Test the enums used in config translation"""

    def test_column_type_enum(self):
        """Test ColumnType enum"""
        assert ColumnType.REGULAR.value == 'regular'
        assert ColumnType.ANCHOR.value == 'anchor'
        assert ColumnType.FOREIGN_KEY.value == 'foreign_key'
        assert ColumnType.MULTI_VALUE.value == 'multi_value'
        assert ColumnType.RELATIONSHIP_CONTEXT.value == 'relationship_context'
        assert ColumnType.EXTERNAL_ONTOLOGY.value == 'external_ontology'

    def test_processing_strategy_enum(self):
        """Test ProcessingStrategy enum"""
        # ENTITY_CENTRIC strategy has been removed
        assert ProcessingStrategy.STREAMING_ENTITY_CENTRIC.value == 'streaming_entity_centric'
        assert ProcessingStrategy.MULTI_PHASE.value == 'multi_phase'
        assert ProcessingStrategy.AUTO.value == 'auto'
