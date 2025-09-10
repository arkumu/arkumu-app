"""
Tests for ChunkedProcessor.

Tests the processor that handles large CSV files by processing them
in memory-efficient chunks with streaming capabilities.
"""
import pytest
import tempfile
import os
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

from arkumu.importer.services.execution.chunked_processor import (
    ChunkedProcessor, StreamingConfig, ChunkInfo, process_large_dataset_chunked
)
from arkumu.importer.services.mapping_consumer import ProcessingStrategy
from arkumu.importer.services.execution.statistics import ExecutionMetrics
from arkumu.metadata.models import Resource


def create_mock_resource(resource_id=1, uri="test://resource"):
    """Helper function to create properly mocked Django Resource instances"""
    mock_resource = Mock(spec=Resource)
    mock_resource.id = resource_id
    mock_resource.uri = uri
    mock_resource._meta = Resource._meta
    mock_resource._state = Mock()
    mock_resource._state.db = 'default'
    return mock_resource


@pytest.mark.django_db
class TestStreamingConfig:
    """Test suite for StreamingConfig"""
    
    def test_streaming_config_defaults(self):
        """Test StreamingConfig default values"""
        config = StreamingConfig()
        
        assert config.chunk_size == 10000
        assert config.max_memory_mb == 200
        assert config.enable_gc is True
        assert config.persist_chunks is True
        assert config.max_pending_relationships == 50000
    
    def test_streaming_config_custom_values(self):
        """Test StreamingConfig with custom values"""
        config = StreamingConfig(
            chunk_size=5000,
            max_memory_mb=100,
            enable_gc=False,
            persist_chunks=False,
            max_pending_relationships=10000
        )
        
        assert config.chunk_size == 5000
        assert config.max_memory_mb == 100
        assert config.enable_gc is False
        assert config.persist_chunks is False
        assert config.max_pending_relationships == 10000


@pytest.mark.django_db
class TestChunkInfo:
    """Test suite for ChunkInfo"""
    
    def test_chunk_info_creation(self):
        """Test ChunkInfo dataclass creation"""
        chunk_info = ChunkInfo(
            chunk_number=1,
            rows_processed=1000,
            memory_usage_mb=50.5,
            processing_time_seconds=12.34,
            resources_created=2500,
            triples_created=5000,
            relationships_created=100,
            errors=0
        )
        
        assert chunk_info.chunk_number == 1
        assert chunk_info.rows_processed == 1000
        assert chunk_info.memory_usage_mb == 50.5
        assert chunk_info.processing_time_seconds == 12.34
        assert chunk_info.resources_created == 2500
        assert chunk_info.triples_created == 5000
        assert chunk_info.relationships_created == 100
        assert chunk_info.errors == 0


@pytest.mark.django_db
class TestChunkedProcessor:
    """Test suite for ChunkedProcessor"""
    
    def test_initialization(self, test_organization, test_base_uri, streaming_config):
        """Test ChunkedProcessor initialization"""
        processor = ChunkedProcessor(
            organization=test_organization,
            base_uri=test_base_uri,
            streaming_config=streaming_config
        )
        
        assert processor.institution == test_organization.code
        assert processor.organization == test_organization
        assert processor.base_uri == test_base_uri
        assert processor.streaming_config is streaming_config
        
        # Verify component initialization
        assert processor.statistics is not None
        assert processor.mapping_processor is not None
        
        # Verify streaming state
        assert processor.entity_cache == {}
        assert processor.pending_relationships == []
        assert processor.processed_chunks == []
    
    def test_initialization_with_default_config(self, test_organization_code, test_base_uri):
        """Test initialization with default streaming config"""
        processor = ChunkedProcessor(
            institution=test_organization_code,
            base_uri=test_base_uri
        )
        
        assert isinstance(processor.streaming_config, StreamingConfig)
        assert processor.streaming_config.chunk_size == 10000  # Default value
    
    def test_chunk_list_data(self, chunked_processor, large_csv_data):
        """Test chunking of in-memory list data"""
        chunked_processor.streaming_config.chunk_size = 100
        
        chunks = list(chunked_processor._chunk_list_data(large_csv_data))
        
        # Should create multiple chunks
        assert len(chunks) == 10  # 1000 rows / 100 chunk_size
        
        # Each chunk should have correct size
        for i, chunk in enumerate(chunks[:-1]):  # All but last chunk
            assert len(chunk) == 100
        
        # Last chunk might be smaller
        assert len(chunks[-1]) <= 100
        
        # Total rows should match original
        total_rows = sum(len(chunk) for chunk in chunks)
        assert total_rows == len(large_csv_data)
    
    def test_chunk_list_data_small_dataset(self, chunked_processor, sample_csv_data):
        """Test chunking with dataset smaller than chunk size"""
        chunked_processor.streaming_config.chunk_size = 100
        
        chunks = list(chunked_processor._chunk_list_data(sample_csv_data))
        
        # Should create single chunk
        assert len(chunks) == 1
        assert len(chunks[0]) == len(sample_csv_data)
    
    def test_chunk_list_data_empty_dataset(self, chunked_processor):
        """Test chunking with empty dataset"""
        chunks = list(chunked_processor._chunk_list_data([]))
        
        # Should create no chunks
        assert len(chunks) == 0
    
    @patch('polars.scan_csv')
    def test_read_csv_chunks_from_file(self, mock_scan_csv, chunked_processor):
        """Test reading CSV file in chunks"""
        # Mock polars lazy DataFrame
        mock_lazy_df = Mock()
        mock_lazy_df.select.return_value.collect.return_value.item.return_value = 500  # Total rows
        
        # Mock chunked data
        mock_chunk_df = Mock()
        mock_chunk_df.to_dicts.return_value = [{"id": "1", "name": "Test"}] * 100
        mock_lazy_df.slice.return_value.collect.return_value = mock_chunk_df
        
        mock_scan_csv.return_value = mock_lazy_df
        
        chunked_processor.streaming_config.chunk_size = 100
        
        # Test with real file path
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("id,name\n1,Test\n2,Test2\n")
            temp_file = f.name
        
        try:
            chunks = list(chunked_processor._read_csv_chunks_from_file(temp_file))
            
            # Should create multiple chunks
            assert len(chunks) == 5  # 500 rows / 100 chunk_size
            
            # Each chunk should have data
            for chunk in chunks:
                assert len(chunk) == 100
                assert isinstance(chunk, list)
                assert isinstance(chunk[0], dict)
            
        finally:
            os.unlink(temp_file)
    
    def test_read_csv_chunks_nonexistent_file(self, chunked_processor):
        """Test reading from nonexistent file"""
        chunks = list(chunked_processor._read_csv_chunks_from_file("nonexistent.csv"))
        
        # Should return empty generator
        assert len(chunks) == 0
    
    @patch('psutil.Process')
    def test_get_memory_usage(self, mock_process, chunked_processor):
        """Test memory usage monitoring"""
        # Mock memory info
        mock_memory_info = Mock()
        mock_memory_info.rss = 100 * 1024 * 1024  # 100 MB in bytes
        mock_process.return_value.memory_info.return_value = mock_memory_info
        
        memory_mb = chunked_processor._get_memory_usage_mb()
        
        assert memory_mb == 100.0  # Should be 100 MB
    
    @patch('psutil.Process')
    def test_get_memory_usage_error_handling(self, mock_process, chunked_processor):
        """Test memory usage error handling"""
        mock_process.side_effect = Exception("Process error")
        
        memory_mb = chunked_processor._get_memory_usage_mb()
        
        assert memory_mb == 0.0  # Should return 0 on error
    
    def test_cleanup_memory(self, chunked_processor):
        """Test memory cleanup operations"""
        # Fill entity cache beyond limit
        for i in range(15000):
            chunked_processor.entity_cache[f"entity_{i}"] = Mock()
        
        # Fill pending relationships beyond limit
        for i in range(60000):
            chunked_processor.pending_relationships.append({"id": i})
        
        initial_cache_size = len(chunked_processor.entity_cache)
        initial_relationships_size = len(chunked_processor.pending_relationships)
        
        chunked_processor._cleanup_memory()
        
        # Entity cache should be trimmed
        assert len(chunked_processor.entity_cache) <= 5000
        assert len(chunked_processor.entity_cache) < initial_cache_size
        
        # Pending relationships should be trimmed
        assert len(chunked_processor.pending_relationships) <= chunked_processor.streaming_config.max_pending_relationships
        assert len(chunked_processor.pending_relationships) < initial_relationships_size
    
    @patch('gc.collect')
    def test_cleanup_memory_garbage_collection(self, mock_gc_collect, chunked_processor):
        """Test garbage collection during cleanup"""
        mock_gc_collect.return_value = 100  # Objects collected
        
        chunked_processor._cleanup_memory()
        
        # Garbage collection should be called when enabled
        mock_gc_collect.assert_called_once()
    
    def test_cleanup_memory_gc_disabled(self, chunked_processor):
        """Test cleanup when garbage collection is disabled"""
        chunked_processor.streaming_config.enable_gc = False
        
        with patch('gc.collect') as mock_gc_collect:
            chunked_processor._cleanup_memory()
            
            # Garbage collection should not be called
            mock_gc_collect.assert_not_called()
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_process_large_csv_sources_list_data(self, mock_triple_objects, mock_resource_objects,
                                               chunked_processor, execution_config_simple, large_csv_data):
        """Test processing large CSV sources with list data"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        # Set small chunk size for testing
        chunked_processor.streaming_config.chunk_size = 100
        
        csv_sources = {"test_dataset": large_csv_data}
        
        metrics = chunked_processor.process_large_csv_sources(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Verify processing completed
        assert isinstance(metrics, ExecutionMetrics)
        
        # Should have processed multiple chunks
        assert len(chunked_processor.processed_chunks) > 1
        
        # Verify chunk info
        for chunk_info in chunked_processor.processed_chunks:
            assert isinstance(chunk_info, ChunkInfo)
            assert chunk_info.chunk_number > 0
            assert chunk_info.rows_processed > 0
    
    def test_process_large_csv_sources_file_data(self, chunked_processor, execution_config_simple):
        """Test processing with CSV file paths"""
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("id,name,age\n")
            for i in range(500):
                f.write(f"{i},Person_{i},{20 + i % 50}\n")
            temp_file = f.name
        
        try:
            csv_sources = {"test_dataset": temp_file}
            
            with patch.object(chunked_processor, '_read_csv_chunks_from_file') as mock_read_chunks:
                # Mock chunk data
                mock_chunks = [
                    [{"id": str(i), "name": f"Person_{i}", "age": str(20 + i)} for i in range(100)]
                    for _ in range(5)  # 5 chunks
                ]
                mock_read_chunks.return_value = iter(mock_chunks)
                
                metrics = chunked_processor.process_large_csv_sources(
                    execution_config=execution_config_simple,
                    csv_sources=csv_sources,
                    strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
                )
                
                assert isinstance(metrics, ExecutionMetrics)
                mock_read_chunks.assert_called_once_with(temp_file)
        
        finally:
            os.unlink(temp_file)
    
    def test_process_large_csv_sources_unsupported_data_type(self, chunked_processor, execution_config_simple):
        """Test processing with unsupported CSV source type"""
        csv_sources = {"test_dataset": 12345}  # Invalid type
        
        metrics = chunked_processor.process_large_csv_sources(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Should handle gracefully
        assert isinstance(metrics, ExecutionMetrics)
        assert len(chunked_processor.processed_chunks) == 0
    
    def test_process_large_csv_sources_missing_dataset(self, chunked_processor, execution_config_simple):
        """Test processing when dataset is missing from CSV sources"""
        csv_sources = {"other_dataset": [{"data": "value"}]}
        
        metrics = chunked_processor.process_large_csv_sources(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        # Should handle missing dataset gracefully
        assert isinstance(metrics, ExecutionMetrics)
        assert len(chunked_processor.processed_chunks) == 0
    
    def test_process_large_csv_sources_strategy_fallback(self, chunked_processor, execution_config_simple):
        """Test processing with non-streaming strategy falls back"""
        csv_sources = {"test_dataset": [{"name": "Test"}]}
        
        metrics = chunked_processor.process_large_csv_sources(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.MULTI_PHASE  # Non-streaming strategy
        )
        
        # Should fall back to streaming strategy
        assert isinstance(metrics, ExecutionMetrics)
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_memory_management_during_processing(self, mock_triple_objects, mock_resource_objects,
                                                chunked_processor, execution_config_simple):
        """Test memory management during chunk processing"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        # Set low memory limit to trigger cleanup
        chunked_processor.streaming_config.max_memory_mb = 1  # Very low limit
        chunked_processor.streaming_config.chunk_size = 50
        
        # Create data that will trigger memory cleanup
        large_dataset = [
            {"id": str(i), "name": f"Person_{i}", "data": "x" * 1000}
            for i in range(200)
        ]
        
        csv_sources = {"test_dataset": large_dataset}
        
        with patch.object(chunked_processor, '_get_memory_usage_mb') as mock_memory:
            mock_memory.return_value = 100  # Always report high memory usage
            
            with patch.object(chunked_processor, '_cleanup_memory') as mock_cleanup:
                metrics = chunked_processor.process_large_csv_sources(
                    execution_config=execution_config_simple,
                    csv_sources=csv_sources,
                    strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
                )
                
                # Cleanup should be called due to high memory usage
                assert mock_cleanup.called
                assert isinstance(metrics, ExecutionMetrics)
    
    def test_resolve_pending_relationships_final(self, chunked_processor):
        """Test final resolution of pending relationships"""
        # Add some pending relationships
        chunked_processor.pending_relationships = [
            {"source": "entity1", "target": "entity2"},
            {"source": "entity2", "target": "entity3"},
            {"source": "entity3", "target": "entity1"}
        ]
        
        initial_count = len(chunked_processor.pending_relationships)
        
        chunked_processor._resolve_pending_relationships_final()
        
        # Relationships should be cleared after resolution
        assert len(chunked_processor.pending_relationships) == 0
        assert initial_count > 0  # Verify we had relationships to resolve
    
    def test_get_processing_summary_no_chunks(self, chunked_processor):
        """Test processing summary with no chunks processed"""
        summary = chunked_processor.get_processing_summary()
        
        assert summary["status"] == "no_chunks_processed"
    
    def test_get_processing_summary_with_chunks(self, chunked_processor):
        """Test processing summary with processed chunks"""
        # Add some processed chunks
        chunked_processor.processed_chunks = [
            ChunkInfo(
                chunk_number=1,
                rows_processed=100,
                memory_usage_mb=50.0,
                processing_time_seconds=10.0,
                resources_created=200,
                triples_created=400,
                relationships_created=50,
                errors=0
            ),
            ChunkInfo(
                chunk_number=2,
                rows_processed=100,
                memory_usage_mb=55.0,
                processing_time_seconds=12.0,
                resources_created=200,
                triples_created=400,
                relationships_created=50,
                errors=1
            )
        ]
        
        summary = chunked_processor.get_processing_summary()
        
        assert summary["chunks_processed"] == 2
        assert summary["total_rows_processed"] == 200
        assert summary["total_resources_created"] == 400
        assert summary["total_triples_created"] == 800
        assert summary["total_processing_time_seconds"] == 22.0
        assert summary["average_memory_usage_mb"] == 52.5
        assert summary["rows_per_second"] == 200 / 22.0
        
        # Should include chunk details
        assert "chunk_details" in summary
        assert len(summary["chunk_details"]) == 2


@pytest.mark.django_db
class TestChunkedProcessorPerformance:
    """Performance tests for ChunkedProcessor"""
    
    @patch('arkumu.metadata.models.Resource.objects')
    @patch('arkumu.metadata.models.triples.Triple.objects')
    def test_chunked_processing_performance(self, mock_triple_objects, mock_resource_objects,
                                          chunked_processor, execution_config_simple, performance_test_data):
        """Test chunked processing performance with large dataset"""
        # Mock database operations
        mock_resource = create_mock_resource()
        mock_resource_objects.get_or_create.return_value = (mock_resource, True)
        mock_resource_objects.bulk_create.return_value = []
        mock_resource_objects.filter.return_value.select_related.return_value = []
        mock_triple_objects.bulk_create.return_value = []
        
        # Use subset for testing
        test_data = performance_test_data[:5000]
        
        # Set reasonable chunk size
        chunked_processor.streaming_config.chunk_size = 500
        
        csv_sources = {"test_dataset": test_data}
        
        import time
        start_time = time.time()
        
        metrics = chunked_processor.process_large_csv_sources(
            execution_config=execution_config_simple,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify processing completed
        assert isinstance(metrics, ExecutionMetrics)
        assert len(chunked_processor.processed_chunks) == 10  # 5000 / 500
        
        # Should complete in reasonable time
        assert processing_time < 120.0  # Should complete within 2 minutes
        
        summary = chunked_processor.get_processing_summary()
        print(f"Chunked processing: {summary['total_rows_processed']} rows in {processing_time:.2f}s")
        print(f"Processing rate: {summary['rows_per_second']:.1f} rows/second")
    
    def test_memory_efficiency(self, chunked_processor, execution_config_simple):
        """Test memory efficiency of chunked processing"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Create large dataset
        large_dataset = [
            {"id": str(i), "name": f"Person_{i}", "data": "x" * 500}
            for i in range(10000)
        ]
        
        # Set small chunk size to test memory efficiency
        chunked_processor.streaming_config.chunk_size = 100
        
        csv_sources = {"memory_test": large_dataset}
        
        with patch.object(chunked_processor.mapping_processor, 'process_with_execution_config') as mock_process:
            mock_process.return_value = ExecutionMetrics()
            
            metrics = chunked_processor.process_large_csv_sources(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable for chunked processing
        assert memory_increase < 200  # Should not use excessive memory
        
        print(f"Memory usage: {initial_memory:.1f}MB -> {final_memory:.1f}MB (+{memory_increase:.1f}MB)")


@pytest.mark.django_db
class TestProcessLargeDatasetChunkedFunction:
    """Test the convenience function for chunked processing"""
    
    @patch('arkumu.importer.services.mapping_consumer.MappingAdapter')
    def test_process_large_dataset_chunked_function(self, mock_mapping_adapter):
        """Test the convenience function"""
        # Mock mapping adapter
        mock_execution_config = Mock()
        mock_execution_config.datasets = [Mock(dataset_name="test_dataset")]
        mock_mapping_adapter.return_value.translate_to_execution_config.return_value = mock_execution_config
        
        # Create temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("id,name\n1,Test\n2,Test2\n")
            temp_file = f.name
        
        try:
            with patch('arkumu.importer.services.execution.chunked_processor.ChunkedProcessor') as mock_processor_class:
                mock_processor = Mock()
                mock_processor.process_large_csv_sources.return_value = ExecutionMetrics()
                mock_processor.get_processing_summary.return_value = {
                    "chunks_processed": 1,
                    "total_rows_processed": 2
                }
                mock_processor_class.return_value = mock_processor
                
                result = process_large_dataset_chunked(
                    mapping_id=1,
                    csv_file_path=temp_file,
                    institution="TEST_ORG",
                    base_uri="http://test.org",
                    chunk_size=1000,
                    max_memory_mb=100
                )
                
                # Verify function completed
                assert isinstance(result, dict)
                assert "chunks_processed" in result
                assert "execution_metrics" in result
                
                # Verify processor was configured correctly
                mock_processor_class.assert_called_once()
                mock_processor.process_large_csv_sources.assert_called_once()
        
        finally:
            os.unlink(temp_file)
    
    @patch('arkumu.importer.services.mapping_consumer.MappingAdapter')
    def test_process_large_dataset_chunked_function_custom_params(self, mock_mapping_adapter):
        """Test convenience function with custom parameters"""
        mock_execution_config = Mock()
        mock_execution_config.datasets = [Mock(dataset_name="custom_dataset")]
        mock_mapping_adapter.return_value.translate_to_execution_config.return_value = mock_execution_config
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("id,name\n1,Test\n")
            temp_file = f.name
        
        try:
            with patch('arkumu.importer.services.execution.chunked_processor.ChunkedProcessor') as mock_processor_class:
                mock_processor = Mock()
                mock_processor.process_large_csv_sources.return_value = ExecutionMetrics()
                mock_processor.get_processing_summary.return_value = {"test": "summary"}
                mock_processor_class.return_value = mock_processor
                
                result = process_large_dataset_chunked(
                    mapping_id=123,
                    csv_file_path=temp_file,
                    institution="CUSTOM_ORG",
                    base_uri="http://custom.org",
                    chunk_size=5000,
                    max_memory_mb=150
                )
                
                # Verify processor was created with custom parameters
                call_args = mock_processor_class.call_args
                assert call_args[1]['institution'] == "CUSTOM_ORG"
                assert call_args[1]['base_uri'] == "http://custom.org"
                
                # Verify streaming config
                streaming_config = call_args[1]['streaming_config']
                assert streaming_config.chunk_size == 5000
                assert streaming_config.max_memory_mb == 150
        
        finally:
            os.unlink(temp_file)


@pytest.mark.django_db
class TestChunkedProcessorEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_chunk_processing_with_errors(self, chunked_processor, execution_config_simple):
        """Test chunk processing when errors occur"""
        csv_sources = {"test_dataset": [{"name": "Test"}]}
        
        with patch.object(chunked_processor, '_process_chunk_with_streaming_entity_centric') as mock_process:
            mock_process.side_effect = Exception("Processing error")
            
            metrics = chunked_processor.process_large_csv_sources(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
            
            # Should handle errors gracefully
            assert isinstance(metrics, ExecutionMetrics)
            assert chunked_processor.statistics.current_metrics.errors >= 1
    
    def test_memory_cleanup_with_empty_caches(self, chunked_processor):
        """Test memory cleanup with empty caches"""
        # Ensure caches are empty
        chunked_processor.entity_cache = {}
        chunked_processor.pending_relationships = []
        
        # Should not raise errors
        chunked_processor._cleanup_memory()
        
        assert len(chunked_processor.entity_cache) == 0
        assert len(chunked_processor.pending_relationships) == 0
    
    def test_csv_file_reading_with_invalid_csv(self, chunked_processor):
        """Test CSV file reading with invalid CSV content"""
        # Create file with invalid CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("invalid,csv,content\nwith,unmatched,quotes\"\nand,missing,fields")
            temp_file = f.name
        
        try:
            with patch('polars.scan_csv') as mock_scan_csv:
                mock_scan_csv.side_effect = Exception("CSV parsing error")
                
                chunks = list(chunked_processor._read_csv_chunks_from_file(temp_file))
                
                # Should handle CSV parsing errors gracefully
                assert len(chunks) == 0
        
        finally:
            os.unlink(temp_file)
    
    def test_processing_with_very_small_chunks(self, chunked_processor, execution_config_simple):
        """Test processing with very small chunk size"""
        chunked_processor.streaming_config.chunk_size = 1  # Single row per chunk
        
        csv_sources = {"test_dataset": [{"name": "Test1"}, {"name": "Test2"}]}
        
        with patch.object(chunked_processor.mapping_processor, 'process_with_execution_config') as mock_process:
            mock_process.return_value = ExecutionMetrics()
            
            metrics = chunked_processor.process_large_csv_sources(
                execution_config=execution_config_simple,
                csv_sources=csv_sources,
                strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
            
            # Should handle small chunks
            assert isinstance(metrics, ExecutionMetrics)
            assert len(chunked_processor.processed_chunks) == 2  # One chunk per row
    
    def test_processing_summary_with_zero_time(self, chunked_processor):
        """Test processing summary when processing time is zero"""
        chunked_processor.processed_chunks = [
            ChunkInfo(
                chunk_number=1,
                rows_processed=100,
                memory_usage_mb=50.0,
                processing_time_seconds=0.0,  # Zero time
                resources_created=200,
                triples_created=400,
                relationships_created=50,
                errors=0
            )
        ]
        
        summary = chunked_processor.get_processing_summary()
        
        # Should handle zero time gracefully
        assert summary["rows_per_second"] == 0
        assert summary["total_processing_time_seconds"] == 0.0