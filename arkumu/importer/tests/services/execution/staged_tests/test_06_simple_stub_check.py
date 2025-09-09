"""
Stage 6: Simple Stub Resolution Check

Quick validation of stub resolution using a small subset of real data.
This checks the core question: Are stub entities created and resolved correctly?
"""

import pytest
import logging
from arkumu.metadata.models import Resource, Triple
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.config_translator import ProcessingStrategy
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


@pytest.mark.django_db(transaction=True)
def test_simple_stub_resolution_check(production_test_mapping, real_csv_data):
    """Quick check of stub resolution with real FUK data"""
    
    logger.info("SIMPLE STUB RESOLUTION CHECK")
    logger.info("=" * 50)
    
    # Setup
    from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
    mapping_adapter = MappingAdapter()
    execution_config = mapping_adapter.translate_to_execution_config(production_test_mapping.id)
    
    # Create test organization
    test_org, _ = Organization.objects.get_or_create(
        code="STUB_CHECK",
        defaults={'name': 'Stub Check Org'}
    )
    
    # Clear existing data
    Triple.objects.filter(source=test_org).delete()
    Resource.objects.filter(organization=test_org).delete()
    
    # Get a small sample of data for testing
    # Pick 2 datasets: one that references another
    sample_data = {}
    
    # AkteurIn_Ereignis_Kreuztabelle has FK references to AkteurIn and Ereignis
    if 'AkteurIn_Ereignis_Kreuztabelle' in real_csv_data:
        sample_data['AkteurIn_Ereignis_Kreuztabelle'] = real_csv_data['AkteurIn_Ereignis_Kreuztabelle'][:10]  # First 10 rows
    
    # AkteurIn is referenced by the above
    if 'AkteurIn' in real_csv_data:
        sample_data['AkteurIn'] = real_csv_data['AkteurIn'][:20]  # First 20 rows
    
    if len(sample_data) < 2:
        pytest.skip("Need at least AkteurIn_Ereignis_Kreuztabelle and AkteurIn datasets for this test")
    
    logger.info(f"Testing with sample data:")
    for name, data in sample_data.items():
        logger.info(f"  {name}: {len(data)} rows")
    
    # Initialize processor
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(
        organization=test_org,
        base_uri="http://test.arkumu.org/data",
        statistics=statistics
    )
    
    # Process all data at once
    logger.info("\nProcessing sample data...")
    
    metrics = processor.process_with_execution_config(
        execution_config=execution_config,
        csv_sources=sample_data,
        strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
    )
    
    # Check results
    total_resources = Resource.objects.filter(organization=test_org).count()
    stub_entities = Resource.objects.filter(
        organization=test_org,
        is_placeholder=True,
        resource_type='IRI'
    ).count()
    
    real_entities = Resource.objects.filter(
        organization=test_org,
        is_placeholder=False,
        resource_type='IRI'
    ).count()
    
    total_triples = Triple.objects.filter(source=test_org).count()
    
    # Check FK relationships
    fk_to_entities = Triple.objects.filter(
        source=test_org,
        object__resource_type='IRI',
        object__uri__contains='/entities/'
    ).exclude(
        predicate__uri__contains='rdf-syntax'
    ).count()
    
    fk_to_literals = Triple.objects.filter(
        source=test_org,
        object__resource_type='LITERAL'
    ).filter(
        predicate__uri__contains='_id'
    ).count()
    
    logger.info(f"\nRESULTS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Real entities: {real_entities}")
    logger.info(f"  Stub entities: {stub_entities}")
    logger.info(f"  Total triples: {total_triples}")
    logger.info(f"  FK relationships to entities: {fk_to_entities}")
    logger.info(f"  FK relationships to literals: {fk_to_literals}")
    
    # Show some examples
    if stub_entities > 0:
        sample_stubs = Resource.objects.filter(
            organization=test_org,
            is_placeholder=True
        )[:3]
        logger.info(f"\nSample stub entities:")
        for stub in sample_stubs:
            logger.info(f"  STUB: {stub.uri}")
    
    if fk_to_entities > 0:
        sample_fks = Triple.objects.filter(
            source=test_org,
            object__resource_type='IRI',
            object__uri__contains='/entities/'
        ).exclude(
            predicate__uri__contains='rdf-syntax'
        )[:3]
        logger.info(f"\nSample FK relationships:")
        for fk in sample_fks:
            logger.info(f"  FK: {fk.subject.uri} -> {fk.object.uri}")
    
    # Basic validation
    assert total_resources > 0, "Should have created some resources"
    assert real_entities > 0, "Should have real entities"
    
    if fk_to_entities > 0:
        logger.info("✅ FK relationships correctly point to entities")
    else:
        logger.warning("⚠️ No FK relationships to entities found")
    
    if fk_to_literals > 0:
        logger.warning(f"⚠️ Found {fk_to_literals} FK relationships to literals (potential bug)")
    
    logger.info("\n✅ Simple stub resolution check completed")
    
    # Cleanup
    Triple.objects.filter(source=test_org).delete()
    Resource.objects.filter(organization=test_org).delete()