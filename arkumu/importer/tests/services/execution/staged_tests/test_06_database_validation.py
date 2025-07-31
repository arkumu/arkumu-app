"""
Stage 6: Database Validation Tests - Persistence and Integrity Verification

This test validates that the processing engine correctly persisted data to the database
and maintains data integrity. It re-runs processing specifically to verify database operations.

## What This Stage Tests

### Components Under Test
- **MappingAwareProcessor**: Database persistence operations
- **Resource Model**: Entity object creation and storage
- **Triple Model**: Relationship object creation and storage

### Database Validation Workflow
1. Re-run processing with focus on database persistence
2. Query test database for created objects with test-specific URIs
3. Validate object counts match reported ExecutionMetrics
4. Verify data integrity and relationships

### Key Validation Points
- ✅ Resource count in database matches ExecutionMetrics.resources_created
- ✅ Triple count in database matches ExecutionMetrics.triples_created  
- ✅ High percentage of Resources have associated Triples (not orphaned)
- ✅ No invalid Triples (missing subjects/predicates)
- ✅ Test isolation maintained with test-specific URI patterns
- ✅ Performance metrics within acceptable thresholds

## Why This Stage Matters

This ensures that processing doesn't just run successfully but actually persists
valid data to the database. Without proper database validation, successful processing
metrics could mask persistence failures.

## Expected Results
- 250+ Resources created with test URIs
- 400+ Triples created linking Resources
- High resource-triple coverage (minimal orphans)
- Complete test isolation and cleanup
"""
import pytest
import logging
from datetime import datetime, timezone
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.importer.services.mapping_consumer.config_translator import ProcessingStrategy
from arkumu.metadata.models import Resource
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)


class TestDatabaseValidation:
    """Test database validation after processing"""
    
    def setup_method(self):
        """Setup test environment"""
        self.mapping_adapter = MappingAdapter()
        self.statistics = ExecutionStatistics()
        self.processor = None
        self.test_uri_pattern = "test.arkumu.org"
    def test_resource_creation_validation(self, production_test_mapping, real_csv_data, execution_statistics):
        """Test that resources are correctly created in database"""
        # Execute processing first
        execution_config = self.mapping_adapter.translate_to_execution_config(production_test_mapping.id)
        
        processor = MappingAwareProcessor(
            organization=production_test_mapping.organization,
            base_uri="http://test.arkumu.org/data",
            statistics=execution_statistics
        )
        self.processor = processor
        
        # Process the data
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=real_csv_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Validate resource creation
        logger.info("=== RESOURCE CREATION VALIDATION ===")
        
        # Query test resources
        test_resources = Resource.objects.filter(uri__contains=self.test_uri_pattern)
        resource_count = test_resources.count()
        
        logger.info(f"Resources created in database: {resource_count}")
        logger.info(f"Resources reported by metrics: {metrics.resources_created}")
        
        # Verify resource creation
        assert resource_count > 0, "Must create resources in database"
        assert resource_count == metrics.resources_created, "Database count must match metrics"
        
        # Sample resource validation
        if resource_count > 0:
            sample_resources = test_resources[:5]
            for i, resource in enumerate(sample_resources):
                logger.info(f"  Resource {i+1}: {resource.uri}")
                assert resource.uri is not None, "Resource must have URI"
                assert self.test_uri_pattern in resource.uri, "Resource must have test URI pattern"
                
                # Verify resource attributes
                assert hasattr(resource, 'resource_type'), "Resource must have type"
                if resource.resource_type:
                    logger.info(f"    Type: {resource.resource_type.name}")
        
        logger.info("Resource creation validation completed")
        return resource_count
    
    @pytest.mark.django_db(transaction=True)
    def test_triple_creation_validation(self, production_test_mapping, real_csv_data, execution_statistics):
        """Test that triples are correctly created in database"""
        # Execute processing first
        execution_config = self.mapping_adapter.translate_to_execution_config(production_test_mapping.id)
        
        processor = MappingAwareProcessor(
            organization=production_test_mapping.organization,
            base_uri="http://test.arkumu.org/data",
            statistics=execution_statistics
        )
        self.processor = processor
        
        # Process the data
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=real_csv_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Validate triple creation
        logger.info("=== TRIPLE CREATION VALIDATION ===")
        
        # Query test triples (subjects with test URI pattern)
        test_triples = Triple.objects.filter(subject__uri__contains=self.test_uri_pattern)
        triple_count = test_triples.count()
        
        logger.info(f"Triples created in database: {triple_count}")
        logger.info(f"Triples reported by metrics: {metrics.triples_created}")
        
        # Verify triple creation
        assert triple_count > 0, "Must create triples in database"
        assert triple_count == metrics.triples_created, "Database count must match metrics"
        
        # Sample triple validation
        if triple_count > 0:
            sample_triples = test_triples[:5]
            for i, triple in enumerate(sample_triples):
                logger.info(f"  Triple {i+1}: {triple.subject.uri} -> {triple.predicate.name} -> {triple.object}")
                
                # Verify triple structure
                assert triple.subject is not None, "Triple must have subject"
                assert triple.predicate is not None, "Triple must have predicate"
                assert triple.object is not None, "Triple must have object"
                
                # Verify test URI pattern
                assert self.test_uri_pattern in triple.subject.uri, "Subject must have test URI pattern"
        
        logger.info("Triple creation validation completed")
        return triple_count
    
    @pytest.mark.django_db(transaction=True)
    def test_data_integrity_validation(self, production_test_mapping, real_csv_data, execution_statistics):
        """Test data integrity of created database objects"""
        # Execute processing first
        execution_config = self.mapping_adapter.translate_to_execution_config(production_test_mapping.id)
        
        processor = MappingAwareProcessor(
            organization=production_test_mapping.organization,
            base_uri="http://test.arkumu.org/data",
            statistics=execution_statistics
        )
        self.processor = processor
        
        # Process the data
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=real_csv_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Validate data integrity
        logger.info("=== DATA INTEGRITY VALIDATION ===")
        
        # Get all test data
        test_resources = Resource.objects.filter(uri__contains=self.test_uri_pattern)
        test_triples = Triple.objects.filter(subject__uri__contains=self.test_uri_pattern)
        
        resource_count = test_resources.count()
        triple_count = test_triples.count()
        
        logger.info(f"Total test resources: {resource_count}")
        logger.info(f"Total test triples: {triple_count}")
        
        # Verify basic integrity
        assert resource_count > 0, "Must have resources"
        assert triple_count > 0, "Must have triples"
        
        # Check resource-triple relationships
        resources_with_triples = 0
        orphaned_resources = 0
        
        for resource in test_resources[:10]:  # Check first 10 resources
            related_triples = Triple.objects.filter(subject=resource)
            if related_triples.exists():
                resources_with_triples += 1
            else:
                orphaned_resources += 1
        
        logger.info(f"Resources with triples: {resources_with_triples}")
        logger.info(f"Orphaned resources: {orphaned_resources}")
        
        # Verify most resources have associated triples
        if resource_count > 0:
            resource_coverage = resources_with_triples / min(10, resource_count) * 100
            logger.info(f"Resource-triple coverage: {resource_coverage:.1f}%")
            
            # Most resources should have triples (allowing some orphans)
            assert resource_coverage > 50, "Most resources should have associated triples"
        
        # Check triple validity
        invalid_triples = 0
        for triple in test_triples[:10]:  # Check first 10 triples
            if not triple.subject or not triple.predicate:
                invalid_triples += 1
        
        logger.info(f"Invalid triples found: {invalid_triples}")
        assert invalid_triples == 0, "Should not have invalid triples"
        
        logger.info("Data integrity validation completed")
        
    @pytest.mark.django_db(transaction=True) 
    def test_processing_performance_validation(self, production_test_mapping, real_csv_data, execution_statistics):
        """Test processing performance metrics"""
        # Execute processing with timing
        start_time = datetime.now(timezone.utc)
        
        execution_config = self.mapping_adapter.translate_to_execution_config(production_test_mapping.id)
        
        processor = MappingAwareProcessor(
            organization=production_test_mapping.organization,
            base_uri="http://test.arkumu.org/data",
            statistics=execution_statistics
        )
        self.processor = processor
        
        # Process the data
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=real_csv_data,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        end_time = datetime.now(timezone.utc)
        total_processing_time = (end_time - start_time).total_seconds()
        
        # Performance validation
        logger.info("=== PROCESSING PERFORMANCE VALIDATION ===")
        logger.info(f"Total processing time: {total_processing_time:.2f} seconds")
        logger.info(f"Rows processed: {metrics.rows_processed}")
        logger.info(f"Resources created: {metrics.resources_created}")
        logger.info(f"Triples created: {metrics.triples_created}")
        
        # Calculate performance metrics
        if metrics.rows_processed > 0:
            rows_per_second = metrics.rows_processed / total_processing_time
            resources_per_second = metrics.resources_created / total_processing_time
            triples_per_second = metrics.triples_created / total_processing_time
            
            logger.info(f"Performance metrics:")
            logger.info(f"  Rows per second: {rows_per_second:.2f}")
            logger.info(f"  Resources per second: {resources_per_second:.2f}")
            logger.info(f"  Triples per second: {triples_per_second:.2f}")
            
            # Performance assertions
            assert rows_per_second > 0, "Must process rows"
            assert total_processing_time < 300.0, "Must complete within 5 minutes"
        
        logger.info("Performance validation completed")