"""
Chunked Processor

Handles large CSV files by processing them in memory-efficient chunks.
"""

import logging
import gc
import psutil
import os
from typing import Dict, Any, List, Optional, Union, Iterator, Tuple
from dataclasses import dataclass
from datetime import datetime
import polars as pl
from pathlib import Path

from arkumu.importer.services.mapping_consumer import ExecutionConfig, ProcessingStrategy
from .mapping_aware_processor import MappingAwareProcessor, ProcessingContext
from .statistics import ExecutionStatistics, ExecutionMetrics

logger = logging.getLogger(__name__)


@dataclass
class ChunkInfo:
    """Information about a processed chunk"""
    chunk_number: int
    rows_processed: int
    memory_usage_mb: float
    processing_time_seconds: float
    resources_created: int
    triples_created: int
    relationships_created: int
    errors: int


@dataclass
class StreamingConfig:
    """Configuration for streaming processing"""
    chunk_size: int = 10000  # Default 10K rows per chunk
    max_memory_mb: int = 200  # Max memory before cleanup
    enable_gc: bool = True    # Enable garbage collection between chunks
    persist_chunks: bool = True  # Persist each chunk immediately
    max_pending_relationships: int = 50000  # Max relationships to queue


class ChunkedProcessor:
    """
    Process large CSV files in memory-efficient chunks.
    
    This processor handles datasets that are too large to fit in memory
    by breaking them into smaller chunks and processing incrementally.
    """
    
    def __init__(self,
                 organization,
                 base_uri: str,
                 streaming_config: Optional[StreamingConfig] = None):
        """
        Initialize chunked processor.
        
        Args:
            organization: Organization object for ownership tracking
            base_uri: Base URI for resource generation
            streaming_config: Configuration for streaming behavior
        """
        self.organization = organization
        self.institution = organization.code if organization else "default"
        self.base_uri = base_uri
        self.streaming_config = streaming_config or StreamingConfig()
        
        # Initialize statistics
        self.statistics = ExecutionStatistics()
        
        # Initialize mapping-aware processor
        self.mapping_processor = MappingAwareProcessor(
            organization=organization,
            base_uri=base_uri,
            statistics=self.statistics
        )
        
        # Streaming state
        self.entity_cache = {}  # Limited cache for FK resolution
        self.pending_relationships = []  # Bounded relationship queue
        self.processed_chunks = []  # Track chunk processing info
        
    def process_large_csv_sources(self,
                                execution_config: ExecutionConfig,
                                csv_sources: Dict[str, Union[str, List[Dict]]],
                                strategy: ProcessingStrategy = ProcessingStrategy.STREAMING_ENTITY_CENTRIC) -> ExecutionMetrics:
        """
        Process large CSV sources using chunked streaming.
        
        Args:
            execution_config: Complete execution configuration
            csv_sources: Dictionary mapping dataset names to CSV file paths or data
            strategy: Processing strategy (must be streaming-compatible)
            
        Returns:
            Aggregated execution metrics
        """
        logger.info(f"Starting chunked processing for {len(csv_sources)} datasets")
        
        if strategy not in [ProcessingStrategy.STREAMING_ENTITY_CENTRIC, ProcessingStrategy.MULTI_PHASE]:
            logger.warning(f"Strategy {strategy} not optimal for large datasets, using STREAMING_ENTITY_CENTRIC")
            strategy = ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        
        # Use dependency resolver to determine correct processing order
        from ..mapping_consumer import DependencyResolver
        dependency_resolver = DependencyResolver()
        phases = dependency_resolver.resolve_dependencies(execution_config)
        
        # Process datasets in dependency order (phase by phase)
        logger.info(f"Processing {len(phases)} dependency phases with {len(csv_sources)} datasets")
        
        for phase in phases:
            logger.info(f"🔄 Processing {phase.phase_name}: {len(phase.datasets)} datasets")
            for dataset_name in phase.datasets:
                # Find the dataset config for this dataset
                dataset_config = None
                for config in execution_config.datasets:
                    if config.dataset_name == dataset_name:
                        dataset_config = config
                        break
                
                if not dataset_config:
                    logger.warning(f"No dataset config found for: {dataset_name}")
                    continue
            dataset_name = dataset_config.dataset_name
            
            if dataset_name not in csv_sources:
                logger.warning(f"No CSV source for dataset: {dataset_name}")
                continue
            
            csv_source = csv_sources[dataset_name]
            
            # Process this dataset in chunks
            self._process_dataset_in_chunks(dataset_config, csv_source, execution_config)
        
        # Resolve any remaining relationships
        self._resolve_pending_relationships_final()
        
        logger.info(f"Chunked processing completed: {len(self.processed_chunks)} chunks processed")
        return self.statistics.current_metrics
    
    def _process_dataset_in_chunks(self,
                                 dataset_config,
                                 csv_source: Union[str, List[Dict]],
                                 execution_config: ExecutionConfig):
        """Process a single dataset in chunks"""
        
        dataset_name = dataset_config.dataset_name
        logger.info(f"Processing dataset '{dataset_name}' in chunks of {self.streaming_config.chunk_size}")
        
        # Handle different CSV source types
        if isinstance(csv_source, str):
            # File path - use chunked reading
            chunk_iterator = self._read_csv_chunks_from_file(csv_source)
        elif isinstance(csv_source, list):
            # In-memory data - chunk it
            chunk_iterator = self._chunk_list_data(csv_source)
        else:
            logger.error(f"Unsupported CSV source type: {type(csv_source)}")
            return
        
        chunk_number = 0
        
        # Process each chunk
        for chunk_data in chunk_iterator:
            chunk_number += 1
            chunk_start_time = datetime.now()
            
            logger.info(f"Processing chunk {chunk_number} for dataset '{dataset_name}' ({len(chunk_data)} rows)")
            
            # Create processing context for this chunk
            chunk_context = ProcessingContext(
                execution_config=execution_config,
                current_dataset=dataset_name,
                all_csv_sources={dataset_name: chunk_data},
                entity_cache=self.entity_cache,  # Shared cache across chunks
                processed_datasets=set()
            )
            
            try:
                # Process chunk with mapping-aware processor
                chunk_metrics = self._process_chunk_with_streaming_entity_centric(
                    dataset_config, chunk_data, chunk_context
                )
                
                # Update statistics
                self.statistics.merge_metrics(chunk_metrics)
                
                # Memory management
                memory_usage = self._get_memory_usage_mb()
                chunk_processing_time = (datetime.now() - chunk_start_time).total_seconds()
                
                # Record chunk info
                chunk_info = ChunkInfo(
                    chunk_number=chunk_number,
                    rows_processed=len(chunk_data),
                    memory_usage_mb=memory_usage,
                    processing_time_seconds=chunk_processing_time,
                    resources_created=chunk_metrics.resources_created,
                    triples_created=chunk_metrics.triples_created,
                    relationships_created=chunk_metrics.relationships_created,
                    errors=chunk_metrics.errors
                )
                self.processed_chunks.append(chunk_info)
                
                logger.info(f"Chunk {chunk_number} completed: "
                          f"{chunk_info.resources_created} resources, "
                          f"{chunk_info.triples_created} triples, "
                          f"{memory_usage:.1f}MB memory")
                
                # Memory cleanup if needed
                if memory_usage > self.streaming_config.max_memory_mb:
                    self._cleanup_memory()
                
            except Exception as e:
                logger.error(f"Failed to process chunk {chunk_number} for dataset '{dataset_name}': {e}")
                self.statistics.current_metrics.errors += 1
    
    def _process_chunk_with_streaming_entity_centric(self,
                                         dataset_config,
                                         chunk_data: List[Dict],
                                         context: ProcessingContext) -> ExecutionMetrics:
        """Process a chunk using streaming entity-centric approach"""
        
        # Create a fresh metrics instance for this chunk
        chunk_statistics = ExecutionStatistics()
        chunk_processor = MappingAwareProcessor(
            institution=self.institution,
            base_uri=self.base_uri,
            statistics=chunk_statistics
        )
        
        # Share the entity cache and pending relationships
        chunk_processor.entity_cache = self.entity_cache
        chunk_processor.pending_relationships = self.pending_relationships
        
        # Process this chunk
        return chunk_processor.process_with_execution_config(
            context.execution_config,
            context.all_csv_sources,
            ProcessingStrategy.STREAMING_ENTITY_CENTRIC  # Use streaming entity-centric for each chunk
        )
    
    def _read_csv_chunks_from_file(self, file_path: str) -> Iterator[List[Dict]]:
        """Read CSV file in chunks using polars"""
        
        if not os.path.exists(file_path):
            logger.error(f"CSV file not found: {file_path}")
            return
        
        logger.info(f"Reading CSV file in chunks: {file_path}")
        
        try:
            # Use polars for chunked reading with lazy evaluation
            lazy_df = pl.scan_csv(
                file_path,
                infer_schema_length=0,  # Read everything as strings to avoid type issues
                null_values=[]  # Don't convert to null
            )
            
            # Get total row count for chunking
            total_rows = lazy_df.select(pl.count()).collect().item()
            
            # Process in chunks
            for offset in range(0, total_rows, self.streaming_config.chunk_size):
                chunk_df = lazy_df.slice(offset, self.streaming_config.chunk_size).collect()
                
                # Convert to list of dictionaries
                chunk_data = chunk_df.to_dicts()
                yield chunk_data
                
        except Exception as e:
            logger.error(f"Failed to read CSV file in chunks: {e}")
            # Return empty generator for graceful error handling
            return
    
    def _chunk_list_data(self, data: List[Dict]) -> Iterator[List[Dict]]:
        """Chunk in-memory list data"""
        
        chunk_size = self.streaming_config.chunk_size
        
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            yield chunk
    
    def _resolve_pending_relationships_final(self):
        """Resolve any remaining pending relationships using MappingAwareProcessor logic"""
        
        if not self.pending_relationships:
            logger.info("No pending FK relationships to resolve")
            return
        
        logger.info(f"🔗 FINAL FK RESOLUTION: Resolving {len(self.pending_relationships)} pending relationships after all datasets completed")
        
        # Create a processor instance to handle FK resolution
        final_processor = MappingAwareProcessor(
            institution=self.institution,
            base_uri=self.base_uri,
            statistics=self.statistics
        )
        
        # Share the accumulated entity cache and pending relationships
        final_processor.entity_cache = self.entity_cache
        final_processor.pending_relationships = self.pending_relationships
        
        # Create a context for FK resolution (datasets are already processed)
        context = ProcessingContext(
            execution_config=None,  # Not needed for FK resolution only
            current_dataset="",
            all_csv_sources={},  # Not needed for FK resolution
            entity_cache=self.entity_cache,
            processed_datasets=set()  # All datasets are considered processed at this point
        )
        
        # Use the processor's FK resolution logic
        try:
            final_processor._resolve_pending_relationships(context)
            logger.info("🔗 FINAL FK RESOLUTION: Successfully completed")
        except Exception as e:
            logger.error(f"🔗 FINAL FK RESOLUTION: Failed with error: {e}")
            self.statistics.current_metrics.errors += 1
    
    def _cleanup_memory(self):
        """Perform memory cleanup between chunks"""
        
        logger.info("Performing memory cleanup...")
        
        # Limit entity cache size (keep most recent entities)
        if len(self.entity_cache) > 10000:
            # Keep only the last 5000 entities
            sorted_entities = list(self.entity_cache.items())
            self.entity_cache = dict(sorted_entities[-5000:])
            logger.info(f"Trimmed entity cache to {len(self.entity_cache)} entities")
        
        # Limit pending relationships
        if len(self.pending_relationships) > self.streaming_config.max_pending_relationships:
            # Process or discard oldest relationships
            excess = len(self.pending_relationships) - self.streaming_config.max_pending_relationships
            discarded_relationships = self.pending_relationships[:excess]
            self.pending_relationships = self.pending_relationships[excess:]
            logger.warning(f"Discarded {len(discarded_relationships)} pending relationships due to memory limits")
        
        # Force garbage collection
        if self.streaming_config.enable_gc:
            collected = gc.collect()
            logger.info(f"Garbage collection freed {collected} objects")
    
    def _get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return memory_info.rss / 1024 / 1024  # Convert bytes to MB
        except Exception:
            return 0.0
    
    def get_processing_summary(self) -> Dict[str, Any]:
        """Get summary of chunked processing"""
        
        if not self.processed_chunks:
            return {"status": "no_chunks_processed"}
        
        total_rows = sum(chunk.rows_processed for chunk in self.processed_chunks)
        total_resources = sum(chunk.resources_created for chunk in self.processed_chunks)
        total_triples = sum(chunk.triples_created for chunk in self.processed_chunks)
        total_time = sum(chunk.processing_time_seconds for chunk in self.processed_chunks)
        avg_memory = sum(chunk.memory_usage_mb for chunk in self.processed_chunks) / len(self.processed_chunks)
        
        return {
            "chunks_processed": len(self.processed_chunks),
            "total_rows_processed": total_rows,
            "total_resources_created": total_resources,
            "total_triples_created": total_triples,
            "total_processing_time_seconds": total_time,
            "average_memory_usage_mb": avg_memory,
            "rows_per_second": total_rows / total_time if total_time > 0 else 0,
            "chunk_details": [
                {
                    "chunk": chunk.chunk_number,
                    "rows": chunk.rows_processed,
                    "resources": chunk.resources_created,
                    "triples": chunk.triples_created,
                    "time_seconds": chunk.processing_time_seconds,
                    "memory_mb": chunk.memory_usage_mb
                }
                for chunk in self.processed_chunks
            ]
        }


def process_large_dataset_chunked(mapping_id: int,
                                csv_file_path: str,
                                institution: str = "DEFAULT",
                                base_uri: str = "http://arkumu.org/data",
                                chunk_size: int = 10000,
                                max_memory_mb: int = 200) -> Dict[str, Any]:
    """
    Convenience function to process a large CSV file in chunks.
    
    Args:
        mapping_id: ID of the mapping configuration
        csv_file_path: Path to the large CSV file
        institution: Institution identifier
        base_uri: Base URI for resource generation
        chunk_size: Number of rows per chunk
        max_memory_mb: Memory limit before cleanup
        
    Returns:
        Processing summary
    """
    from ..mapping_consumer import MappingAdapter
    
    # Load mapping configuration
    mapping_adapter = MappingAdapter()
    execution_config = mapping_adapter.translate_to_execution_config(mapping_id)
    
    # Configure streaming
    streaming_config = StreamingConfig(
        chunk_size=chunk_size,
        max_memory_mb=max_memory_mb,
        enable_gc=True,
        persist_chunks=True
    )
    
    # Initialize chunked processor
    processor = ChunkedProcessor(
        institution=institution,
        base_uri=base_uri,
        streaming_config=streaming_config
    )
    
    # Determine dataset name from mapping (use first dataset or filename)
    dataset_name = execution_config.datasets[0].dataset_name if execution_config.datasets else Path(csv_file_path).stem
    
    # Process the file
    csv_sources = {dataset_name: csv_file_path}
    metrics = processor.process_large_csv_sources(execution_config, csv_sources)
    
    # Get summary
    summary = processor.get_processing_summary()
    summary["execution_metrics"] = {
        "resources_created": metrics.resources_created,
        "triples_created": metrics.triples_created,
        "relationships_created": metrics.relationships_created,
        "rows_processed": metrics.rows_processed,
        "cells_processed": metrics.cells_processed,
        "errors": metrics.errors
    }
    
    return summary