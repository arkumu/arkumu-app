"""
Test to verify FK relationships create IRI triples, not literal triples.
"""
import pytest
from django.test import TestCase
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.resource_manager import ResourceManager
from arkumu.importer.services.execution.statistics import ExecutionStatistics


@pytest.mark.django_db
class TestFKTripleCreation(TestCase):
    """Test that FK relationships create proper IRI-to-IRI triples"""
    
    def test_fk_relationship_creates_iri_triple_not_literal(self):
        """Verify FK relationships create resource-to-resource links, not literal values"""
        
        # Create a mapping with a simple FK relationship
        mapping_data = {
            'workspace_columns': {
                'ereignis::ereignis_id': {
                    'dataset': 'ereignis',
                    'name': 'ereignis_id',
                    'arkumu_type': 'identifier',
                    'column_name': 'ereignis_id'
                },
                'person::person_id': {
                    'dataset': 'person', 
                    'name': 'person_id',
                    'arkumu_type': 'identifier',
                    'column_name': 'person_id'
                },
                'person::ereignis_id_fk': {
                    'dataset': 'person',
                    'name': 'ereignis_id_fk', 
                    'arkumu_type': 'ereignis',
                    'column_name': 'ereignis_id_fk',
                    'fk_config': {
                        'target_dataset': 'ereignis',
                        'target_column': 'ereignis_id'
                    }
                }
            },
            'workspace_datasets': ['ereignis', 'person'],
            'fk_relationships': {
                'person.ereignis_id_fk -> ereignis.ereignis_id': {
                    'source_dataset': 'person',
                    'source_column': 'ereignis_id_fk',
                    'target_dataset': 'ereignis', 
                    'target_column': 'ereignis_id',
                    'relationship_type': 'ereignis'
                }
            }
        }
        
        # Create CSV data
        csv_data = {
            'ereignis': [['ereignis_id'], ['123']],
            'person': [['person_id', 'ereignis_id_fk'], ['456', '123']]
        }
        
        # Translate mapping
        translator = ConfigTranslator()
        execution_config = translator.translate_mapping_config(mapping_data)
        
        # Verify FK column is detected correctly
        fk_columns = [col for col in execution_config.column_configurations.values() 
                      if col.column_type.value == 'foreign_key']
        assert len(fk_columns) == 1, f"Expected 1 FK column, got {len(fk_columns)}"
        
        fk_col = fk_columns[0]
        assert fk_col.column_name == 'ereignis_id_fk'
        assert fk_col.is_fk == True
        assert fk_col.fk_config is not None
        
        # Execute the mapping
        statistics = ExecutionStatistics("test-org")
        processor = MappingAwareProcessor(
            execution_config=execution_config,
            organization="test-org",
            statistics=statistics
        )
        
        result = processor.process(csv_data)
        
        # Verify execution succeeded
        assert result.success == True, f"Execution failed: {result.details}"
        
        # Check that resources were created
        ereignis_entity = Resource.objects.filter(
            uri__contains='ereignis/123',
            resource_type=ResourceType.IRI
        ).first()
        assert ereignis_entity is not None, "Ereignis entity not found"
        
        person_entity = Resource.objects.filter(
            uri__contains='person/456', 
            resource_type=ResourceType.IRI
        ).first()
        assert person_entity is not None, "Person entity not found"
        
        # KEY TEST: Find the FK relationship triple
        fk_triples = Triple.objects.filter(
            subject=person_entity,
            object=ereignis_entity  # This should be an IRI resource, not a literal
        )
        
        assert fk_triples.exists(), "No FK relationship triple found linking person to ereignis"
        
        fk_triple = fk_triples.first()
        
        # Verify it's an IRI-to-IRI relationship, not a literal
        assert fk_triple.object.resource_type == ResourceType.IRI, \
            f"FK triple object should be IRI, got {fk_triple.object.resource_type}"
        
        # Verify the relationship points to the correct entity
        assert '123' in fk_triple.object.uri, \
            f"FK triple should point to ereignis/123, got {fk_triple.object.uri}"
        
        print(f"✅ FK relationship correctly created: {fk_triple.subject.uri} -[{fk_triple.predicate.uri}]-> {fk_triple.object.uri}")
        print(f"✅ Object type: {fk_triple.object.resource_type} (should be IRI)")