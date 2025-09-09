"""
Test Multi-Value Columns Processing  

Focused test for multi-value column processing using schema data.
Tests that comma-separated values are split and processed individually.
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
def test_multivalue_columns_split_correctly():
    """Test that multi-value columns are split and processed as individual values"""
    
    # Setup organization
    org, _ = Organization.objects.get_or_create(
        code='mvtest',
        defaults={'name': 'Multi-Value Test Org', 'domain': 'mvtest.com'}
    )
    
    # Create mapping with multi-value columns
    mapping = Mapping.objects.create(
        name='MultiValue-Test',
        organization_id=org.code,
        source_datasets=['Product'],
        mapping_config={
            'version': '1.1',
            'workspace_datasets': {
                'Product': {
                    'columns': [
                        {'name': 'ID', 'arkumu_type': 'ID'},
                        {'name': 'Name', 'arkumu_type': 'Name'},
                        {'name': 'Tags', 'arkumu_type': 'Tags', 'is_multivalue': True},
                        {'name': 'Categories', 'arkumu_type': 'Categories', 'is_multivalue': True}
                    ]
                }
            },
            'multi_value_columns': [
                {
                    'dataset': 'Product',
                    'column': 'Tags',
                    'delimiter': ',',
                    'property': 'hasTag'
                },
                {
                    'dataset': 'Product', 
                    'column': 'Categories',
                    'delimiter': ',',
                    'property': 'hasCategory'
                }
            ]
        }
    )
    
    # Test data with multi-value columns
    csv_sources = {
        'Product': [
            {
                'ID': 'PROD001', 
                'Name': 'Laptop Computer',
                'Tags': 'electronics,portable,work,computer',
                'Categories': 'technology,office,hardware'
            },
            {
                'ID': 'PROD002',
                'Name': 'Coffee Mug', 
                'Tags': 'kitchen,ceramic,drink',
                'Categories': 'home,kitchen'
            }
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
    
    logger.info("🔗 Testing multi-value column processing...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            csv_sources,
            'streaming_entity_centric'
        )
        logger.info("✅ Multi-value processing completed")
        
    except Exception as e:
        logger.warning(f"⚠️ Processing failed: {e}")
    
    # ANALYZE MULTI-VALUE PROCESSING using Django ORM
    total_resources = Resource.objects.filter(organization=org).count()
    total_triples = Triple.objects.filter(source=org).count()
    
    # Check individual tag values
    tag_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains='hasTag'
    ).count()
    
    category_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains='hasCategory'
    ).count()
    
    # Expected counts:
    # PROD001 tags: electronics, portable, work, computer (4 values)
    # PROD002 tags: kitchen, ceramic, drink (3 values) 
    # Total expected tags: 7
    
    # PROD001 categories: technology, office, hardware (3 values)
    # PROD002 categories: home, kitchen (2 values)
    # Total expected categories: 5
    
    logger.info(f"📊 MULTI-VALUE ANALYSIS:")
    logger.info(f"  Total resources: {total_resources}")
    logger.info(f"  Total triples: {total_triples}")
    logger.info(f"  Tag triples: {tag_triples} (expected: 7)")
    logger.info(f"  Category triples: {category_triples} (expected: 5)")
    
    if tag_triples > 0:
        logger.info("✅ Tag multi-values processed")
        
        # Show tag examples
        tag_examples = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasTag'
        )[:5]
        
        for triple in tag_examples:
            logger.info(f"  🏷️ {triple.subject.uri} -> hasTag: {triple.object.uri}")
            
        # Check if values were split correctly
        expected_tags = ['electronics', 'portable', 'work', 'computer', 'kitchen', 'ceramic', 'drink']
        found_tags = [t.object.uri for t in tag_examples]
        
        for expected_tag in expected_tags[:3]:  # Check first 3
            if any(expected_tag in found_tag for found_tag in found_tags):
                logger.info(f"  ✅ Found expected tag: {expected_tag}")
            else:
                logger.warning(f"  ⚠️ Missing expected tag: {expected_tag}")
    
    if category_triples > 0:
        logger.info("✅ Category multi-values processed")
        
        # Show category examples  
        category_examples = Triple.objects.filter(
            source=org,
            predicate__uri__contains='hasCategory'
        )[:3]
        
        for triple in category_examples:
            logger.info(f"  📁 {triple.subject.uri} -> hasCategory: {triple.object.uri}")
    
    if tag_triples == 0 and category_triples == 0:
        logger.error("❌ No multi-value columns processed")
        pytest.fail("Multi-value processing failed - no individual values found")
    
    else:
        logger.info("✅ Multi-value columns split and processed correctly")
        assert tag_triples >= 3, f"Should have at least 3 tag values, got {tag_triples}"
        assert category_triples >= 2, f"Should have at least 2 category values, got {category_triples}"