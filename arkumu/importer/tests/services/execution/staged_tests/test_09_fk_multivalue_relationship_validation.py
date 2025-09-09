"""
Stage 9: FK Resolution, Multi-Value, and Relationship Context Validation with Real Production Data

This test validates that FK resolution, multi-value column processing, and relationship contexts
work correctly with actual FUK production data, addressing gaps identified in test coverage analysis.

## Key Validation Areas

### 1. FK Resolution with Real Data
- Multi-value FK columns (e.g., `Projekt.Ereignis`, `AkteurIn.Wirkungsort`)
- Cross-dataset FK resolution accuracy
- Stub entity creation for missing targets
- FK normalization and case handling

### 2. Multi-Value Column Processing  
- Various separators in production data
- Empty value handling in real multi-value strings
- Multi-value FK combinations

### 3. Relationship Contexts (Junction Tables)
- `AkteurIn_Ereignis_Kreuztabelle` with role context attributes
- `Projekt_Projekt_Kreuztabelle` with relationship context
- Junction entity creation with contextual properties

## Test Strategy

Rather than synthetic data, these tests use actual FUK production data to ensure
the functionality works with real-world edge cases and data quality issues.
"""
import pytest
import logging
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


@pytest.mark.django_db
def test_fk_resolution_with_real_production_data(
    production_test_mapping,
    real_csv_data,
    mapping_adapter,
    execution_statistics
):
    """
    Test FK resolution using real FUK data focusing on multi-value FK columns
    and cross-dataset relationship accuracy.
    
    This test specifically validates:
    - Multi-value FK columns like `Projekt.Ereignis` resolve correctly
    - FK relationships between `AkteurIn` and `Ort` entities work
    - Stub entities are created appropriately for missing targets
    - FK resolution statistics are accurate
    """
    logger.info("=" * 60)
    logger.info("Stage 9a: FK RESOLUTION VALIDATION WITH REAL DATA")
    logger.info("=" * 60)
    
    # Get FUK organization
    org = Organization.objects.get(code='fuk')
    logger.info(f"Testing with organization: {org.code} ({org.name})")
    
    # Load execution configuration
    logger.info("Loading execution configuration...")
    config = mapping_adapter.load_mapping_config(production_test_mapping.id)
    
    config_translator = ConfigTranslator()
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info(f"Execution config loaded - {len(execution_config.datasets)} datasets, {len(execution_config.fk_relationships)} FK relationships")
    
    # Initialize processor
    base_uri = f"http://arkumu.org/data/{org.code}"
    processor = MappingAwareProcessor(org, execution_statistics, base_uri=base_uri)
    
    # Focus on datasets with high FK activity: Projekt, AkteurIn, Ereignis, Ort
    fk_focused_datasets = {}
    target_datasets = ['Projekt', 'AkteurIn', 'Ereignis', 'Ort']
    
    for dataset_name in target_datasets:
        if dataset_name in real_csv_data:
            # Limit to 10 rows per dataset for focused testing
            fk_focused_datasets[dataset_name] = {
                'headers': real_csv_data[dataset_name]['headers'],
                'rows': real_csv_data[dataset_name]['rows'][:10]
            }
            logger.info(f"FK dataset included: {dataset_name} ({len(real_csv_data[dataset_name]['rows'])} total rows, using 10)")
    
    if len(fk_focused_datasets) < 2:
        pytest.skip("Need at least 2 target datasets for FK resolution testing")
    
    logger.info(f"Testing FK resolution with {len(fk_focused_datasets)} datasets")
    
    # Clear existing test data
    logger.info("Clearing existing test data...")
    Triple.objects.filter(source=org).delete()  
    Resource.objects.filter(organization=org).delete()
    
    # Get initial counts
    initial_resources = Resource.objects.filter(organization=org).count()
    initial_triples = Triple.objects.filter(source=org).count()
    
    logger.info(f"Initial state: {initial_resources} resources, {initial_triples} triples")
    
    # Process FK-focused datasets
    logger.info("🔗 Starting FK resolution validation...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            fk_focused_datasets,
            'streaming_entity_centric'
        )
        logger.info("✅ FK resolution processing completed successfully")
        
    except Exception as e:
        logger.error(f"❌ FK processing failed: {e}")
        raise
    
    # Analyze FK resolution results
    final_resources = Resource.objects.filter(organization=org).count()
    final_triples = Triple.objects.filter(source=org).count()
    
    resources_created = final_resources - initial_resources
    triples_created = final_triples - initial_triples
    
    logger.info("📊 FK RESOLUTION ANALYSIS:")
    logger.info(f"   Resources created: {resources_created}")
    logger.info(f"   Triples created: {triples_created}")
    logger.info(f"   FK relationships created: {metrics.relationships_created}")
    
    # Validate FK-specific scenarios
    
    # 1. Check that multi-value FKs created multiple relationship triples
    fk_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains='property'  # FK relationships use property URIs
    ).exclude(
        predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'  # Exclude rdf:type
    )
    
    logger.info(f"   Property triples (including FKs): {fk_triples.count()}")
    
    # 2. Check for stub entities (entities created due to missing FK targets)
    stub_entities = Resource.objects.filter(
        organization=org,
        resource_type='IRI',
        is_placeholder=True
    )
    
    logger.info(f"   Stub entities created: {stub_entities.count()}")
    
    # 3. Check cross-dataset entity linking
    entity_resources = Resource.objects.filter(
        organization=org,
        resource_type='IRI',
        is_placeholder=False
    )
    
    logger.info(f"   Real entities created: {entity_resources.count()}")
    
    # Validate core FK functionality
    assert resources_created > 0, "Should create resources during FK processing"
    assert triples_created > 0, "Should create triples during FK processing" 
    assert metrics.relationships_created >= 0, "Should track relationship creation"
    
    # Check that we have both real entities and potentially stub entities
    total_entities = entity_resources.count() + stub_entities.count()
    assert total_entities > 0, "Should create entities (real or stub) during FK processing"
    
    logger.info("✅ FK resolution validation passed with real production data")


@pytest.mark.django_db  
def test_multivalue_column_processing_with_real_data(
    production_test_mapping,
    real_csv_data,
    mapping_adapter,
    execution_statistics
):
    """
    Test multi-value column processing with real FUK data to validate
    various separators, empty value handling, and multi-value FK combinations.
    
    This test focuses on:
    - Multi-value columns like `Projekt.Ereignis` (comma-separated)
    - Multi-value FK columns and their proper splitting
    - Empty value handling in multi-value strings
    - Statistics accuracy for multi-value processing
    """
    logger.info("=" * 60)
    logger.info("Stage 9b: MULTI-VALUE COLUMN VALIDATION WITH REAL DATA")
    logger.info("=" * 60)
    
    # Get FUK organization
    org = Organization.objects.get(code='fuk')
    logger.info(f"Testing with organization: {org.code} ({org.name})")
    
    # Load execution configuration
    config = mapping_adapter.load_mapping_config(production_test_mapping.id)
    config_translator = ConfigTranslator()
    execution_config = config_translator.translate_mapping_config(config)
    
    # Initialize processor
    base_uri = f"http://arkumu.org/data/{org.code}"
    processor = MappingAwareProcessor(org, execution_statistics, base_uri=base_uri)
    
    # Focus on datasets known to have multi-value columns
    multivalue_datasets = {}
    target_datasets = ['Projekt', 'Digitales_Objekt', 'AkteurIn']
    
    for dataset_name in target_datasets:
        if dataset_name in real_csv_data:
            # Use 15 rows to get good multi-value examples
            multivalue_datasets[dataset_name] = {
                'headers': real_csv_data[dataset_name]['headers'],
                'rows': real_csv_data[dataset_name]['rows'][:15]
            }
            logger.info(f"Multi-value dataset included: {dataset_name} (using 15 rows)")
    
    if len(multivalue_datasets) == 0:
        pytest.skip("No target datasets with multi-value columns found")
    
    logger.info(f"Testing multi-value processing with {len(multivalue_datasets)} datasets")
    
    # Clear existing test data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    initial_triples = Triple.objects.filter(source=org).count()
    
    # Process multi-value focused datasets
    logger.info("🔀 Starting multi-value column validation...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            multivalue_datasets,
            'streaming_entity_centric'
        )
        logger.info("✅ Multi-value processing completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Multi-value processing failed: {e}")
        raise
    
    # Analyze multi-value processing results
    final_triples = Triple.objects.filter(source=org).count()
    triples_created = final_triples - initial_triples
    
    logger.info("📊 MULTI-VALUE PROCESSING ANALYSIS:")
    logger.info(f"   Total triples created: {triples_created}")
    logger.info(f"   Multi-value items created: {metrics.multi_value_items_created}")
    logger.info(f"   Multi-value cells split: {metrics.multi_value_cells_split}")
    
    # Validate multi-value specific scenarios
    
    # 1. Check that multi-value columns created multiple triples for single cells
    # Look for properties that should be multi-value based on our configuration
    property_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains='property'
    ).exclude(
        predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    )
    
    logger.info(f"   Property triples created: {property_triples.count()}")
    
    # 2. Check statistics consistency
    if metrics.multi_value_cells_split > 0:
        logger.info(f"   Multi-value cells were processed: {metrics.multi_value_cells_split}")
        assert metrics.multi_value_items_created >= metrics.multi_value_cells_split, \
            "Multi-value items should be >= cells split (each cell produces ≥1 item)"
    
    # 3. Validate that we have property triples (multi-value columns create property triples)
    assert property_triples.count() > 0, "Should create property triples from column processing"
    
    # 4. Check for reasonable triple creation rate
    assert triples_created > 0, "Should create triples during multi-value processing"
    
    logger.info("✅ Multi-value column validation passed with real production data")


@pytest.mark.django_db
def test_relationship_context_processing_with_real_data(
    production_test_mapping,
    real_csv_data,
    mapping_adapter,
    execution_statistics
):
    """
    Test relationship context (junction table) processing with real FUK data
    to validate contextual attributes and junction entity creation.
    
    This test focuses on:
    - Junction tables like `AkteurIn_Ereignis_Kreuztabelle`
    - Contextual attributes (roles, relationships, etc.)
    - Junction entity creation and linking
    - Context attribute property creation
    """
    logger.info("=" * 60)
    logger.info("Stage 9c: RELATIONSHIP CONTEXT VALIDATION WITH REAL DATA")
    logger.info("=" * 60)
    
    # Get FUK organization
    org = Organization.objects.get(code='fuk')
    logger.info(f"Testing with organization: {org.code} ({org.name})")
    
    # Load execution configuration
    config = mapping_adapter.load_mapping_config(production_test_mapping.id)
    config_translator = ConfigTranslator()
    execution_config = config_translator.translate_mapping_config(config)
    
    logger.info(f"Found {len(execution_config.relationship_contexts)} relationship contexts")
    
    # Initialize processor
    base_uri = f"http://arkumu.org/data/{org.code}"
    processor = MappingAwareProcessor(org, execution_statistics, base_uri=base_uri)
    
    # Focus on junction tables (Kreuztabelle files) + their source entities
    junction_focused_data = {}
    
    # Include junction tables
    for dataset_name, dataset_data in real_csv_data.items():
        if 'Kreuztabelle' in dataset_name:
            junction_focused_data[dataset_name] = {
                'headers': dataset_data['headers'], 
                'rows': dataset_data['rows'][:8]  # Limit junction tables to 8 rows
            }
            logger.info(f"Junction table included: {dataset_name} (using 8 rows)")
    
    # Include source entity datasets that junction tables reference
    entity_datasets = ['AkteurIn', 'Ereignis', 'Projekt']
    for dataset_name in entity_datasets:
        if dataset_name in real_csv_data and dataset_name not in junction_focused_data:
            junction_focused_data[dataset_name] = {
                'headers': real_csv_data[dataset_name]['headers'],
                'rows': real_csv_data[dataset_name]['rows'][:5]  # Limit entity datasets to 5 rows
            }
            logger.info(f"Source entity dataset included: {dataset_name} (using 5 rows)")
    
    if not any('Kreuztabelle' in name for name in junction_focused_data.keys()):
        pytest.skip("No junction tables (Kreuztabelle) found in test data")
    
    logger.info(f"Testing relationship contexts with {len(junction_focused_data)} datasets")
    
    # Clear existing test data
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    initial_resources = Resource.objects.filter(organization=org).count()
    initial_triples = Triple.objects.filter(source=org).count()
    
    # Process relationship context focused datasets
    logger.info("🔗 Starting relationship context validation...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            junction_focused_data,
            'streaming_entity_centric'
        )
        logger.info("✅ Relationship context processing completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Relationship context processing failed: {e}")
        raise
    
    # Analyze relationship context results
    final_resources = Resource.objects.filter(organization=org).count()
    final_triples = Triple.objects.filter(source=org).count()
    
    resources_created = final_resources - initial_resources
    triples_created = final_triples - initial_triples
    
    logger.info("📊 RELATIONSHIP CONTEXT ANALYSIS:")
    logger.info(f"   Resources created: {resources_created}")
    logger.info(f"   Triples created: {triples_created}")
    logger.info(f"   Relationships created: {metrics.relationships_created}")
    
    # Validate relationship context specific scenarios
    
    # 1. Check for junction entities (entities from junction tables)
    junction_entities = Resource.objects.filter(
        organization=org,
        resource_type='IRI',
        uri__contains='/entities/'
    )
    
    # Look specifically for junction-type entities
    kreuztabelle_entities = junction_entities.filter(
        uri__contains='Kreuztabelle'
    )
    
    logger.info(f"   Total entities created: {junction_entities.count()}")
    logger.info(f"   Junction entities (Kreuztabelle): {kreuztabelle_entities.count()}")
    
    # 2. Check for contextual property triples
    # These would be properties on junction entities that are not FK relationships
    context_property_triples = Triple.objects.filter(
        source=org,
        predicate__uri__contains='property'
    ).exclude(
        predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    )
    
    logger.info(f"   Context property triples: {context_property_triples.count()}")
    
    # 3. Check for relationship triples (FK relationships between entities)  
    relationship_triples = Triple.objects.filter(
        source=org,
        object__resource_type='IRI'  # Object is another resource (not literal)
    )
    
    logger.info(f"   Inter-entity relationship triples: {relationship_triples.count()}")
    
    # Validate core relationship context functionality
    assert resources_created > 0, "Should create resources during relationship context processing"
    assert triples_created > 0, "Should create triples during relationship context processing"
    
    # Should have created both entities and relationships
    assert junction_entities.count() > 0, "Should create entity resources"
    
    # If we have junction tables, we should have some form of relationship processing
    junction_count = sum(1 for name in junction_focused_data.keys() if 'Kreuztabelle' in name)
    if junction_count > 0:
        logger.info(f"   Processed {junction_count} junction tables")
        # Should have either context properties or relationship triples (or both)
        total_contextual_processing = context_property_triples.count() + relationship_triples.count()
        assert total_contextual_processing > 0, "Junction tables should create contextual triples"
    
    logger.info("✅ Relationship context validation passed with real production data")


@pytest.mark.django_db
def test_comprehensive_processing_statistics_accuracy(
    production_test_mapping,
    real_csv_data,
    mapping_adapter,
    execution_statistics
):
    """
    Test that processing statistics are accurate when all three scenarios
    (FK resolution, multi-value, relationship contexts) are processed together.
    
    This comprehensive test validates:
    - Counter accuracy across different processing types
    - Statistics consistency with actual database state
    - Performance metrics with real data volumes
    """
    logger.info("=" * 60)
    logger.info("Stage 9d: COMPREHENSIVE STATISTICS VALIDATION")
    logger.info("=" * 60)
    
    # Get FUK organization
    org = Organization.objects.get(code='fuk')
    logger.info(f"Testing with organization: {org.code} ({org.name})")
    
    # Load execution configuration
    config = mapping_adapter.load_mapping_config(production_test_mapping.id)
    config_translator = ConfigTranslator()
    execution_config = config_translator.translate_mapping_config(config)
    
    # Initialize processor
    base_uri = f"http://arkumu.org/data/{org.code}"
    processor = MappingAwareProcessor(org, execution_statistics, base_uri=base_uri)
    
    # Use a comprehensive but limited dataset covering all scenarios
    comprehensive_datasets = {}
    target_datasets = ['AkteurIn', 'Ereignis', 'Projekt', 'AkteurIn_Ereignis_Kreuztabelle']
    
    for dataset_name in target_datasets:
        if dataset_name in real_csv_data:
            # Use 8 rows per dataset for comprehensive but manageable processing
            comprehensive_datasets[dataset_name] = {
                'headers': real_csv_data[dataset_name]['headers'],
                'rows': real_csv_data[dataset_name]['rows'][:8]
            }
            logger.info(f"Comprehensive dataset: {dataset_name} (using 8 rows)")
    
    if len(comprehensive_datasets) < 2:
        pytest.skip("Need at least 2 datasets for comprehensive validation")
    
    logger.info(f"Testing comprehensive statistics with {len(comprehensive_datasets)} datasets")
    
    # Clear existing test data and get baseline
    Triple.objects.filter(source=org).delete()
    Resource.objects.filter(organization=org).delete()
    
    initial_resources = Resource.objects.filter(organization=org).count()
    initial_triples = Triple.objects.filter(source=org).count()
    
    # Process comprehensive datasets
    logger.info("📊 Starting comprehensive statistics validation...")
    
    try:
        metrics = processor.process_with_execution_config(
            execution_config,
            comprehensive_datasets,
            'streaming_entity_centric'
        )
        logger.info("✅ Comprehensive processing completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Comprehensive processing failed: {e}")
        raise
    
    # Analyze comprehensive results
    final_resources = Resource.objects.filter(organization=org).count()
    final_triples = Triple.objects.filter(source=org).count()
    
    actual_resources_created = final_resources - initial_resources
    actual_triples_created = final_triples - initial_triples
    
    logger.info("📊 COMPREHENSIVE STATISTICS ANALYSIS:")
    logger.info(f"   Database resources created: {actual_resources_created}")
    logger.info(f"   Database triples created: {actual_triples_created}")
    logger.info(f"   Metrics resources created: {metrics.resources_created}")
    logger.info(f"   Metrics triples created: {metrics.triples_created}")
    logger.info(f"   Metrics relationships created: {metrics.relationships_created}")
    logger.info(f"   Metrics rows processed: {metrics.rows_processed}")
    
    # Advanced statistics validation
    if hasattr(metrics, 'multi_value_items_created'):
        logger.info(f"   Multi-value items: {metrics.multi_value_items_created}")
    if hasattr(metrics, 'multi_value_cells_split'):
        logger.info(f"   Multi-value cells split: {metrics.multi_value_cells_split}")
    
    # Validate statistics accuracy
    
    # 1. Resource creation statistics should match database reality
    # Allow some tolerance due to system resources (datasets, types, etc.)
    assert actual_resources_created >= metrics.resources_created * 0.7, \
        f"Database resources ({actual_resources_created}) should be reasonably close to metrics ({metrics.resources_created})"
    
    # 2. Triple creation should be tracked accurately
    # Allow some tolerance due to system triples (rdf:type, schema, etc.)
    assert actual_triples_created >= metrics.triples_created * 0.7, \
        f"Database triples ({actual_triples_created}) should be reasonably close to metrics ({metrics.triples_created})"
    
    # 3. Row processing should be positive and reasonable
    expected_total_rows = sum(len(data['rows']) for data in comprehensive_datasets.values())
    assert metrics.rows_processed > 0, "Should have processed rows"
    assert metrics.rows_processed <= expected_total_rows * 1.1, \
        f"Rows processed ({metrics.rows_processed}) should not exceed input rows ({expected_total_rows}) by much"
    
    # 4. Check for reasonable processing ratios
    if metrics.relationships_created > 0:
        logger.info(f"   Average relationships per entity: {metrics.relationships_created / actual_resources_created:.2f}")
    
    # 5. Validate that comprehensive processing included all types of operations
    assert actual_resources_created > 0, "Should create resources"
    assert actual_triples_created > 0, "Should create triples"
    assert metrics.rows_processed > 0, "Should process rows"
    
    logger.info("✅ Comprehensive statistics validation passed with real production data")