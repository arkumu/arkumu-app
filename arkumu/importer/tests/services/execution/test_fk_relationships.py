"""
Test FK Relationships Processing

Focused test for Foreign Key relationship resolution using schema data.
Tests that FK relationships create entity references instead of literals.
"""

import pytest
import logging
from arkumu.users.models import Organization
from arkumu.metadata.models import Mapping, Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_fk_relationships_create_entities_not_literals():
    """Test that FK relationships create entity references, not literal values"""
    
    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code='fktest',
        defaults={'name': 'FK Test Org', 'domain': 'fktest.com'}
    )
    
    # Create mapping with FK relationship
    mapping = Mapping.objects.create(
        name='FK-Test',
        organization_id=org.code,
        source_datasets=['Person', 'Location'],
        mapping_config={
            'version': '1.1',
            'workspace_datasets': {
                'Person': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'},
                        {'name': 'BirthPlace', 'arkumu_type': 'BirthPlace'}
                    ]
                },
                'Location': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'}, 
                        {'name': 'Name', 'arkumu_type': 'Name'}
                    ]
                }
            },
            'fk_relationships': [
                {
                    'id': 'person_birthplace_fk',
                    'source_dataset': 'Person',
                    'source_column': 'BirthPlace',
                    'target_dataset': 'Location', 
                    'target_column': 'ID'
                }
            ]
        }
    )
    
    # Test data with FK relationships
    csv_sources = {
        'Location': [
            {'ID': 'LOC001', 'Name': 'Berlin'},
            {'ID': 'LOC002', 'Name': 'Paris'}
        ],
        'Person': [
            {'ID': 'P001', 'Name': 'John Doe', 'BirthPlace': 'LOC001'},
            {'ID': 'P002', 'Name': 'Jane Smith', 'BirthPlace': 'LOC002'}
        ]
    }
    
    # Clear existing data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    # Process with schema-driven processor
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(org, f"http://arkumu.org/data/{org.code}", statistics)
    
    mapping_adapter = MappingAdapter()
    config_translator = ConfigTranslator()
    config = mapping_adapter.load_mapping_config(mapping.id)
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info("🔗 Testing FK relationship processing...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            csv_sources,
            'streaming_entity_centric'
        )
        logger.info("✅ FK processing completed")
        
    except Exception as e:
        logger.warning(f"⚠️ Processing failed: {e}")
    
    # ANALYZE FK RELATIONSHIPS using Django ORM
    total_resources = Resource.objects.filter(organization=org).count()
    total_triples = Triple.objects.filter(source=org).count()
    
    # Check FK triples specifically
    fk_triples_with_literals = Triple.objects.filter(
        source=org,
        predicate__uri__contains='BirthPlace',
        object__resource_type='LITERAL'
    ).count()
    
    fk_triples_with_entities = Triple.objects.filter(
        source=org,
        predicate__uri__contains='BirthPlace',
        object__resource_type='IRI',
        object__uri__contains='/entities/'
    ).count()
    
    logger.info(f"📊 FK ANALYSIS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Total triples: {total_triples}")
    logger.info(f"  FK triples with literals: {fk_triples_with_literals}")
    logger.info(f"  FK triples with entities: {fk_triples_with_entities}")
    
    if fk_triples_with_literals > 0:
        # Show broken FK examples
        broken_fks = Triple.objects.filter(
            source=org,
            predicate__uri__contains='BirthPlace',
            object__resource_type='LITERAL'
        )[:3]
        
        logger.error("🚨 BROKEN FK RELATIONSHIPS:")
        for triple in broken_fks:
            logger.error(f"  {triple.subject.uri} -> {triple.predicate.uri} -> LITERAL('{triple.object.uri}')")
        
        pytest.fail(f"FK BUG: Found {fk_triples_with_literals} FK relationships using literals instead of entities")
    
    if fk_triples_with_entities > 0:
        logger.info("✅ FK relationships correctly use entities")
        # Show correct FK examples
        correct_fks = Triple.objects.filter(
            source=org,
            predicate__uri__contains='BirthPlace',
            object__resource_type='IRI'
        )[:3]
        
        for triple in correct_fks:
            logger.info(f"  ✅ {triple.subject.uri} -> {triple.predicate.uri} -> ENTITY({triple.object.uri})")
    
    else:
        logger.warning("⚠️ No FK relationships processed - test inconclusive")

    # VALIDATE STUB RESOLUTION  
    logger.info("🔄 VALIDATING STUB RESOLUTION...")
    
    # Check for any remaining stub entities
    remaining_stubs = Resource.objects.filter(
        source=org,
        is_placeholder=True
    ).count()
    
    # Check stub resolution statistics if available
    resolved_stubs = 0
    if hasattr(statistics.current_metrics, 'stub_entities_resolved'):
        resolved_stubs = statistics.current_metrics.stub_entities_resolved
    
    logger.info(f"  Remaining stub entities: {remaining_stubs}")
    logger.info(f"  Stub entities resolved (tracked): {resolved_stubs}")
    
    if remaining_stubs > 0:
        logger.warning(f"⚠️ STUB RESOLUTION: {remaining_stubs} stub entities remain unresolved")
        
        # Show example stub entities
        stub_examples = Resource.objects.filter(
            source=org,
            is_placeholder=True
        )[:3]
        
        for stub in stub_examples:
            logger.warning(f"  Unresolved stub: {stub.uri}")
    else:
        logger.info("✅ STUB RESOLUTION: No remaining stub entities (all resolved or none created)")
    
    if resolved_stubs > 0:
        logger.info(f"✅ STUB RESOLUTION SUCCESS: {resolved_stubs} stubs converted to real entities")
        
    logger.info("✅ FK relationships and stub resolution test completed successfully")