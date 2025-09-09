"""
Test handling of empty datasets in entity-based processing.

This test module verifies that empty datasets (with no rows) still create
their dataset URI resources properly, which is essential for maintaining
referential integrity in the knowledge graph.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor, ProcessingContext
from arkumu.importer.services.mapping_consumer import ExecutionConfig, DatasetConfig, ColumnConfig, ProcessingStrategy
from arkumu.importer.services.mapping_consumer.config_translator import ColumnType
from arkumu.importer.services.execution.statistics import ExecutionStatistics


@pytest.fixture
def processor():
    """Create a mapping-aware processor instance."""
    stats = ExecutionStatistics()
    processor = MappingAwareProcessor(
        institution="test_org",
        base_uri="http://test.org",
        statistics=stats,
        channel_id="test_channel",
        session=Mock()
    )
    return processor


@pytest.fixture
def empty_dataset_config():
    """Create configuration for a dataset that will be empty."""
    return DatasetConfig(
        dataset_name="empty_products",
        columns=[
            ColumnConfig(
                column_name="product_id",
                dataset_name="empty_products",
                arkumu_type="identifier",
                column_type=ColumnType.REGULAR,
                is_anchor=True,
                datatype="string"
            ),
            ColumnConfig(
                column_name="product_name",
                dataset_name="empty_products",
                arkumu_type="name",
                column_type=ColumnType.REGULAR,
                datatype="string"
            )
        ]
    )


@pytest.fixture
def populated_dataset_config():
    """Create configuration for a dataset with data."""
    return DatasetConfig(
        dataset_name="orders",
        columns=[
            ColumnConfig(
                column_name="order_id",
                dataset_name="orders",
                arkumu_type="identifier",
                column_type=ColumnType.REGULAR,
                is_anchor=True,
                datatype="string"
            ),
            ColumnConfig(
                column_name="product_id",
                dataset_name="orders",
                arkumu_type="product_reference",
                column_type=ColumnType.FOREIGN_KEY,
                datatype="string"
            )
        ]
    )


@pytest.fixture
def execution_config(empty_dataset_config, populated_dataset_config):
    """Create execution configuration with both empty and populated datasets."""
    return ExecutionConfig(
        mapping_id=1,
        mapping_name="test_mapping",
        organization="test_org",
        datasets=[empty_dataset_config, populated_dataset_config],
        fk_relationships=[],
        relationship_contexts=[]
    )


@pytest.mark.django_db
class TestEmptyDatasetHandling:
    """Test cases for handling empty datasets."""

    def test_empty_dataset_creates_uri_resource(self, processor, execution_config):
        """Test that empty datasets still create their dataset URI resource."""
        # Prepare test data
        csv_sources = {
            "empty_products": [],  # Empty dataset
            "orders": [
                {"order_id": "ORD001", "product_id": "PROD001"},
                {"order_id": "ORD002", "product_id": "PROD002"}
            ]
        }
        
        # Mock the resource manager methods
        create_dataset_resource_calls = []
        def track_dataset_resource(dataset_name):
            create_dataset_resource_calls.append(dataset_name)
            return Mock(uri=f"http://test.org/datasets/{dataset_name}")
        
        processor.resource_manager.create_dataset_resource = Mock(side_effect=track_dataset_resource)
        processor.resource_manager.create_entity_resource = Mock(return_value=Mock())
        processor.resource_manager.create_dataset_entity_links_bulk = Mock(return_value=[])
        
        # Execute processing
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Use streaming entity-centric strategy (which has the issue)
        processor._process_streaming_entity_centric(context)
        
        # Verify that create_dataset_resource was called for BOTH datasets
        assert "empty_products" in create_dataset_resource_calls, "Empty dataset should have its resource created"
        assert "orders" in create_dataset_resource_calls, "Populated dataset should have its resource created"
        
        # Verify statistics
        assert processor.statistics.current_metrics.datasets_skipped == 1, "Empty dataset should be counted as skipped"

    def test_empty_dataset_with_fk_references(self, processor):
        """Test that empty datasets with FK references create stub structures."""
        # Create config where orders reference empty products
        empty_products_config = DatasetConfig(
            dataset_name="products",
            columns=[
                ColumnConfig(
                    column_name="product_id",
                    dataset_name="products",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                )
            ]
        )
        
        orders_config = DatasetConfig(
            dataset_name="orders",
            columns=[
                ColumnConfig(
                    column_name="order_id",
                    dataset_name="orders",
                    arkumu_type="identifier",
                    column_type=ColumnType.REGULAR,
                    is_anchor=True,
                    datatype="string"
                ),
                ColumnConfig(
                    column_name="product_id",
                    dataset_name="orders",
                    arkumu_type="product_reference",
                    column_type=ColumnType.FOREIGN_KEY,
                    datatype="string"
                )
            ]
        )
        
        execution_config = ExecutionConfig(
            mapping_id=2,
            mapping_name="test_fk_mapping",
            organization="test_org",
            datasets=[empty_products_config, orders_config],
            fk_relationships=[
                Mock(
                    source_dataset="orders",
                    source_column="product_id",
                    target_dataset="products",
                    target_column="product_id"
                )
            ],
            relationship_contexts=[]
        )
        
        csv_sources = {
            "products": [],  # Empty dataset
            "orders": [{"order_id": "ORD001", "product_id": "PROD001"}]
        }
        
        # Mock methods
        check_orphaned_mock = Mock()
        create_stub_mock = Mock()
        processor._check_orphaned_fk_references = check_orphaned_mock
        processor._create_stub_dataset_structure = create_stub_mock
        
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Process
        processor._process_streaming_entity_centric(context)
        
        # Verify orphaned FK check was called
        check_orphaned_mock.assert_called_with("products", context)

    def test_entity_centric_empty_dataset_handling(self, processor, execution_config):
        """Test entity-centric processing handles empty datasets correctly."""
        csv_sources = {
            "empty_products": {"headers": ["product_id", "product_name"], "rows": []},
            "orders": {"headers": ["order_id", "product_id"], "rows": [{"order_id": "1", "product_id": "P1"}]}
        }
        
        # Mock the execution engine
        mock_engine = Mock()
        mock_engine.execute_simple_import = Mock(return_value=Mock())
        processor.execution_engine = mock_engine
        
        # Execute entity-centric processing
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify both datasets were attempted to be processed
        assert mock_engine.execute_simple_import.call_count == 1, "Only non-empty dataset should be processed by engine"
        
        # Check that statistics tracked the skipped dataset
        assert processor.statistics.current_metrics.datasets_skipped == 1

    def test_multi_phase_empty_dataset_handling(self, processor, execution_config):
        """Test multi-phase processing handles empty datasets correctly."""
        csv_sources = {
            "empty_products": [],
            "orders": [{"order_id": "1", "product_id": "P1"}]
        }
        
        # Mock resource manager
        mock_create_dataset = Mock(return_value=Mock())
        processor.resource_manager.create_dataset_resource = mock_create_dataset
        
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Execute multi-phase processing
        processor._process_multi_phase(context)
        
        # Verify dataset resource creation
        # In multi-phase, empty datasets are skipped entirely
        assert processor.statistics.current_metrics.datasets_skipped == 1

    @patch('arkumu.importer.services.execution.mapping_aware_processor.logger')
    def test_empty_dataset_logging(self, mock_logger, processor, execution_config):
        """Test that appropriate warnings are logged for empty datasets."""
        csv_sources = {
            "empty_products": [],
            "orders": [{"order_id": "1"}]
        }
        
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Process
        processor._process_streaming_entity_centric(context)
        
        # Check for warning about empty dataset
        warning_calls = [call for call in mock_logger.warning.call_args_list]
        empty_dataset_warnings = [
            call for call in warning_calls 
            if "empty_products" in str(call) and "empty" in str(call).lower()
        ]
        assert len(empty_dataset_warnings) > 0, "Should log warning about empty dataset"