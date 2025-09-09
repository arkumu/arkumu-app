"""
Test Stub Resolution

Focused test for verifying that stub entities get properly resolved to real entities.
This tests the critical bug fix where stub entities created during FK processing
should be converted to real entities when the target dataset is processed.
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
def test_stub_resolution_with_fk_relationships():
    """Test that stub entities are converted to real entities when target data is processed"""
    
    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code='stubtest',
        defaults={'name': 'Stub Resolution Test Org', 'domain': 'stubtest.com'}
    )
    
    # Create mapping with FK relationships where target is processed AFTER source
    mapping = Mapping.objects.create(
        name='StubResolution-Test',
        organization_id=org.code,
        source_datasets=['Order', 'Customer'],
        mapping_config={
            'version': '1.1',
            'workspace_datasets': {
                'Order': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Amount', 'arkumu_type': 'Amount'},
                        {'name': 'CustomerID', 'arkumu_type': 'CustomerID'}
                    ]
                },
                'Customer': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'}
                    ]
                }
            },
            'fk_relationships': [
                {
                    'id': 'order_customer_fk',
                    'source_dataset': 'Order',
                    'source_column': 'CustomerID',
                    'target_dataset': 'Customer',
                    'target_column': 'ID'
                }
            ]
        }
    )
    
    # Test data - Order references Customer that doesn't exist yet (will create stub)
    csv_sources = {
        'Order': [
            {'ID': 'O001', 'Amount': '100.50', 'CustomerID': 'C001'},
            {'ID': 'O002', 'Amount': '250.75', 'CustomerID': 'C002'}
        ],
        'Customer': [
            {'ID': 'C001', 'Name': 'Alice Johnson'},
            {'ID': 'C002', 'Name': 'Bob Smith'}
        ]
    }
    
    # Clear existing data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    # Process with controlled order - Order first (creates stubs), then Customer (should resolve stubs)
    statistics = ExecutionStatistics()
    processor = MappingAwareProcessor(org, f"http://arkumu.org/data/{org.code}", statistics)
    
    mapping_adapter = MappingAdapter()
    config_translator = ConfigTranslator()
    config = mapping_adapter.load_mapping_config(mapping.id)
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info("🔗 Testing stub resolution with FK relationships...")
    
    try:
        # Process Order data first - should create stub entities for customers
        order_data = {'Order': csv_sources['Order']}
        processor.process_with_execution_config(
            execution_config,
            order_data,
            'streaming_entity_centric'
        )
        
        # Check that stub entities were created
        stub_customers = Resource.objects.filter(
            organization=org,
            uri__contains='/entities/customer/',
            is_placeholder=True
        ).count()
        
        logger.info(f"📊 After Order processing - Stub customers: {stub_customers}")
        
        # Process Customer data - should resolve stubs to real entities
        customer_data = {'Customer': csv_sources['Customer']}
        processor.process_with_execution_config(
            execution_config,
            customer_data,
            'streaming_entity_centric'
        )
        
        logger.info("✅ Stub resolution processing completed")
        
    except Exception as e:
        logger.error(f"⚠️ Processing failed: {e}")
        raise
    
    # CRITICAL ANALYSIS: Verify stub resolution worked
    total_resources = Resource.objects.filter(organization=org).count()
    
    # Check remaining stub entities (should be 0 after resolution)
    remaining_stubs = Resource.objects.filter(
        organization=org,
        is_placeholder=True
    ).count()
    
    # Check real customer entities
    real_customers = Resource.objects.filter(
        organization=org,
        uri__contains='/entities/customer/',
        is_placeholder=False
    ).count()
    
    # Check FK relationships use entities not literals
    fk_literals = Triple.objects.filter(
        source=org,
        predicate__uri__contains='CustomerID',
        object__resource_type='LITERAL'
    ).count()
    
    fk_entities = Triple.objects.filter(
        source=org,
        predicate__uri__contains='CustomerID',
        object__resource_type='IRI',
        object__uri__contains='/entities/'
    ).count()
    
    # Check statistics for stub resolution
    resolved_stubs = statistics.current_metrics.stub_entities_resolved if hasattr(statistics.current_metrics, 'stub_entities_resolved') else 0
    
    logger.info(f"📊 STUB RESOLUTION ANALYSIS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Remaining stubs: {remaining_stubs}")
    logger.info(f"  Real customers: {real_customers}")
    logger.info(f"  FK literals (BUG): {fk_literals}")
    logger.info(f"  FK entities (CORRECT): {fk_entities}")
    logger.info(f"  Resolved stubs: {resolved_stubs}")
    
    # Test assertions
    assert remaining_stubs == 0, f"Should have no remaining stub entities, found {remaining_stubs}"
    assert real_customers >= 2, f"Should have at least 2 real customer entities, found {real_customers}"
    assert fk_literals == 0, f"FK relationships should not use literals, found {fk_literals}"
    assert fk_entities >= 2, f"FK relationships should use entities, found {fk_entities}"
    
    if resolved_stubs > 0:
        logger.info(f"✅ STUB RESOLUTION SUCCESS: {resolved_stubs} stubs converted to real entities")
    else:
        logger.warning("⚠️ No stub resolution statistics recorded")
    
    # Show correct FK relationship examples
    if fk_entities > 0:
        correct_fks = Triple.objects.filter(
            source=org,
            predicate__uri__contains='CustomerID',
            object__resource_type='IRI'
        )[:2]
        
        logger.info("✅ CORRECT FK RELATIONSHIPS:")
        for triple in correct_fks:
            logger.info(f"  {triple.subject.uri} -> CustomerID -> ENTITY({triple.object.uri})")
    
    logger.info("✅ Stub resolution test completed successfully")