"""
Integration test for empty dataset resource creation.

This test verifies that empty datasets still create their URI resources
during entity-based processing, which is essential for maintaining
referential integrity in the knowledge graph.
"""

import pytest
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor, ProcessingContext
from arkumu.importer.services.mapping_consumer import ExecutionConfig, DatasetConfig, ColumnConfig, ProcessingStrategy
from arkumu.importer.services.mapping_consumer.config_translator import ColumnType
from arkumu.importer.services.execution.statistics import ExecutionStatistics
from arkumu.metadata.models import Resource


@pytest.mark.django_db
class TestEmptyDatasetResourceCreation:
    """Integration tests for empty dataset resource creation."""

    def test_streaming_entity_centric_creates_dataset_resource_for_empty_dataset(self):
        """Test that streaming entity-centric processing creates dataset resources for empty datasets."""
        
        # Setup processor
        stats = ExecutionStatistics()
        processor = MappingAwareProcessor(
            institution="test_org",
            base_uri="http://test.org",
            statistics=stats
        )
        
        # Create minimal configuration
        empty_dataset_config = DatasetConfig(
            dataset_name="empty_products",
            columns=[
                ColumnConfig(
                    column_name="product_id",
                    dataset_name="empty_products",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        populated_dataset_config = DatasetConfig(
            dataset_name="orders",
            columns=[
                ColumnConfig(
                    column_name="order_id",
                    dataset_name="orders",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="test_mapping",
            organization="test_org",
            datasets=[empty_dataset_config, populated_dataset_config],
            fk_relationships=[],
            relationship_contexts=[]
        )
        
        # Prepare test data
        csv_sources = {
            "empty_products": [],  # Empty dataset
            "orders": [{"order_id": "ORD001"}]
        }
        
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Count resources before processing
        resources_before = Resource.objects.count()
        
        # Process with streaming entity-centric strategy
        processor._process_streaming_entity_centric(context)
        
        # Count resources after processing
        resources_after = Resource.objects.count()
        
        # Verify dataset resources were created
        empty_dataset_uri = processor.resource_manager.generate_dataset_uri("empty_products")
        orders_dataset_uri = processor.resource_manager.generate_dataset_uri("orders")
        
        # Check that both dataset resources exist
        assert Resource.objects.filter(uri=empty_dataset_uri).exists(), \
            "Empty dataset should have its dataset resource created"
        assert Resource.objects.filter(uri=orders_dataset_uri).exists(), \
            "Populated dataset should have its dataset resource created"
        
        # Verify statistics
        assert stats.current_metrics.datasets_skipped == 1, \
            "Empty dataset should be counted as skipped"
        assert stats.current_metrics.resources_created > 0, \
            "Resources should have been created"
        
        # Verify both datasets are marked as processed
        assert "empty_products" in context.processed_datasets, \
            "Empty dataset should be marked as processed"
        assert "orders" in context.processed_datasets, \
            "Populated dataset should be marked as processed"

    def test_entity_centric_handles_empty_datasets(self):
        """Test that entity-centric processing properly handles empty datasets."""
        
        # Setup processor
        stats = ExecutionStatistics()
        processor = MappingAwareProcessor(
            institution="test_org",
            base_uri="http://test.org",
            statistics=stats
        )
        
        # Create minimal configuration
        dataset_config = DatasetConfig(
            dataset_name="test_empty",
            columns=[
                ColumnConfig(
                    column_name="id",
                    dataset_name="test_empty",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="test_mapping",
            organization="test_org",
            datasets=[dataset_config],
            fk_relationships=[],
            relationship_contexts=[]
        )
        
        # Process empty dataset
        csv_sources = {"test_empty": []}
        
        # Execute using entity-centric strategy
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify dataset resource was created
        dataset_uri = processor.resource_manager.generate_dataset_uri("test_empty")
        assert Resource.objects.filter(uri=dataset_uri).exists(), \
            "Entity-centric processing should create dataset resource for empty dataset"
        
        # Verify statistics
        assert stats.current_metrics.datasets_skipped == 1, \
            "Empty dataset should be counted as skipped"

    def test_multi_phase_handles_empty_datasets(self):
        """Test that multi-phase processing properly handles empty datasets."""
        
        # Setup processor
        stats = ExecutionStatistics()
        processor = MappingAwareProcessor(
            institution="test_org",
            base_uri="http://test.org",
            statistics=stats
        )
        
        # Create configuration with both empty and populated datasets
        empty_config = DatasetConfig(
            dataset_name="empty_dataset",
            columns=[
                ColumnConfig(
                    column_name="id",
                    dataset_name="empty_dataset",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        populated_config = DatasetConfig(
            dataset_name="populated_dataset",
            columns=[
                ColumnConfig(
                    column_name="id",
                    dataset_name="populated_dataset",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=1,
            mapping_name="test_mapping",
            organization="test_org",
            datasets=[empty_config, populated_config],
            fk_relationships=[],
            relationship_contexts=[]
        )
        
        # Prepare test data
        csv_sources = {
            "empty_dataset": [],
            "populated_dataset": [{"id": "1"}]
        }
        
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Process with multi-phase strategy
        processor._process_multi_phase(context)
        
        # Verify dataset resources
        empty_dataset_uri = processor.resource_manager.generate_dataset_uri("empty_dataset")
        assert Resource.objects.filter(uri=empty_dataset_uri).exists(), \
            "Multi-phase processing should create dataset resource for empty dataset"
        
        # Verify both datasets marked as processed
        assert "empty_dataset" in context.processed_datasets
        assert "populated_dataset" in context.processed_datasets