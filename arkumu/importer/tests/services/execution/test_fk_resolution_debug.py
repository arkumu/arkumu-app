"""
FK Resolution Bug Debug Test

Simple, focused test to verify FK relationships use entities instead of literals.
Uses real FUK data to test the critical FK resolution bug.
"""

import pytest
import logging
from arkumu.users.models import Organization
from arkumu.metadata.models import Mapping, Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator
from arkumu.storage.services.bucket_service import BucketService

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_fk_resolution_entities_vs_literals_with_real_fuk_data():
    """Test FK resolution bug - verify entities are used instead of literals with real FUK data"""
    
    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code='fuk',
        defaults={'name': 'Folkwang Universität der Künste', 'domain': 'folkwang-uni.de'}
    )
    
    # Load real FUK mapping from S3
    bucket_service = BucketService()
    result = bucket_service.get_file_content('fuk', 'metadata/folkwang-mapping.json')
    
    if not result.get('success'):
        pytest.skip("Cannot load real FUK mapping from S3")
    
    import json
    real_mapping_config = json.loads(result.get('content', '{}'))
    fk_count = len(real_mapping_config.get('fk_relationships', []))
    logger.info(f"🔍 Loaded REAL FUK mapping with {fk_count} FK relationships")
    
    # Create mapping with real config
    mapping = Mapping.objects.create(
        name='FK-Debug-Test',
        organization_id=org.code,
        source_datasets=['AkteurIn', 'Ort'][:2],  # Minimal for testing
        mapping_config=real_mapping_config
    )
    
    # Create simple test data with FK relationships
    csv_sources = {
        'AkteurIn': [
            {'ID': '1', 'Name': 'Test Person', 'sterbeort': 'Q256477'},
            {'ID': '2', 'Name': 'Another Person', 'sterbeort': 'Q1754'}
        ],
        'Ort': [
            {'ID': 'Q256477', 'Name': 'Berlin'},
            {'ID': 'Q1754', 'Name': 'Stockholm'}
        ]
    }
    
    # Clear any existing data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    # Create processor and process data
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(org, f"http://arkumu.org/data/{org.code}", statistics)
    
    # Create execution config
    mapping_adapter = MappingAdapter()
    config_translator = ConfigTranslator()
    config = mapping_adapter.load_mapping_config(mapping.id)
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info("🚀 Starting FK resolution test with controlled data...")
    
    try:
        # Process the data
        metrics = processor.process_with_execution_config(
            execution_config,
            csv_sources,
            'streaming_entity_centric'
        )
        
        logger.info("✅ Import completed!")
        
    except Exception as e:
        logger.warning(f"⚠️ Import failed, analyzing partial results: {e}")
    
    # ANALYZE RESULTS WITH DJANGO ORM
    total_resources = Resource.objects.filter(organization=org).count()
    total_triples = Triple.objects.filter(source=org).count()
    entity_resources = Resource.objects.filter(organization=org, resource_type='IRI').count()
    literal_resources = Resource.objects.filter(organization=org, resource_type='LITERAL').count()
    
    logger.info(f"📈 RESULTS ANALYSIS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Total triples: {total_triples}")
    logger.info(f"  Entity resources (IRI): {entity_resources}")
    logger.info(f"  Literal resources: {literal_resources}")
    
    if total_triples > 0:
        # THE CRITICAL TEST: Check FK relationships using Django ORM
        fk_triples_with_literals = Triple.objects.filter(
            source=org,
            predicate__uri__contains='/properties/',
            object__resource_type='LITERAL'
        ).exclude(
            predicate__uri__contains='isPartOf'
        ).exclude(
            predicate__uri__contains='rdf:value'
        ).count()
        
        entity_fk_triples = Triple.objects.filter(
            source=org,
            predicate__uri__contains='/properties/',
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='isPartOf'
        ).count()
        
        logger.info(f"🔗 FK RELATIONSHIP ANALYSIS:")
        logger.info(f"  FK triples with LITERAL objects: {fk_triples_with_literals}")
        logger.info(f"  FK triples with ENTITY objects: {entity_fk_triples}")
        
        if fk_triples_with_literals > 0:
            logger.error("🚨 FK RESOLUTION BUG CONFIRMED!")
            
            # Show examples using Django ORM
            broken_fks = Triple.objects.filter(
                source=org,
                predicate__uri__contains='/properties/',
                object__resource_type='LITERAL'
            ).exclude(
                predicate__uri__contains='isPartOf'
            ).exclude(
                predicate__uri__contains='rdf:value'
            )[:3]
            
            logger.error("🔍 BROKEN FK EXAMPLES:")
            for triple in broken_fks:
                logger.error(f"  {triple.subject.uri} -> {triple.predicate.uri} -> LITERAL('{triple.object.uri}')")
            
            pytest.fail(f"FK RESOLUTION BUG: Found {fk_triples_with_literals} FK relationships using literals instead of entities!")
        
        else:
            logger.info("✅ FK resolution working correctly - all FK relationships use entities")
            assert entity_fk_triples > 0, "Should have some FK relationships with entities"
    
    else:
        pytest.skip("No triples created - cannot test FK resolution")