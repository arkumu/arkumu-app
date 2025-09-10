"""
Import Orchestrator

Main orchestration logic for mapping-driven CSV imports.
"""

import logging
import time
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import traceback

from ..mapping_consumer import MappingAdapter, ExecutionConfig
from ..execution import MappingExecutionEngine
from .strategy_selector import StrategySelector, ProcessingStrategy
from .progress_tracker import ProgressTracker, ProgressUpdate
from .result_aggregator import ResultAggregator, AggregatedResult

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of a mapping-driven import operation"""
    # Basic status
    success: bool
    mapping_id: int
    mapping_name: str
    organization: str
    
    # Execution details
    strategy_used: str
    execution_time_seconds: float
    start_time: datetime
    end_time: datetime
    
    # Processing results
    datasets_processed: int
    total_resources_created: int = 0
    total_triples_created: int = 0
    total_rows_processed: int = 0
    total_cells_processed: int = 0
    
    # Phase-wise results
    phase_results: List[Dict[str, Any]] = field(default_factory=list)
    dataset_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Error handling
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Performance metrics
    peak_memory_usage_mb: Optional[float] = None
    average_rows_per_second: Optional[float] = None
    
    def add_error(self, error: str):
        """Add an error message"""
        self.errors.append(error)
        self.success = False
        
    def add_warning(self, warning: str):
        """Add a warning message"""
        self.warnings.append(warning)
    
    def get_summary(self) -> str:
        """Get a human-readable summary"""
        if self.success:
            return (f"Successfully processed {self.datasets_processed} datasets "
                   f"in {self.execution_time_seconds:.1f}s using {self.strategy_used} strategy. "
                   f"Created {self.total_resources_created} resources and {self.total_triples_created} triples.")
        else:
            return (f"Import failed after {self.execution_time_seconds:.1f}s. "
                   f"{len(self.errors)} errors, {len(self.warnings)} warnings.")


class ImportOrchestrator:
    """
    Orchestrates complete mapping-driven import workflows.
    
    This is the main entry point for executing mappings. It coordinates
    between the mapping consumer, strategy selector, and execution engine
    to provide a unified interface for CSV imports.
    """
    
    def __init__(self, 
                 institution: str = "DEFAULT",
                 base_uri: str = "http://arkumu.org/data",
                 enable_progress_tracking: bool = True):
        """
        Initialize the import orchestrator.
        
        Args:
            institution: Institution code for URI generation
            base_uri: Base URI for resource generation
            enable_progress_tracking: Whether to enable progress tracking
        """
        self.institution = institution
        self.base_uri = base_uri
        self.enable_progress_tracking = enable_progress_tracking
        
        # Initialize components
        self.mapping_adapter = MappingAdapter()
        self.strategy_selector = StrategySelector()
        self.result_aggregator = ResultAggregator()
        
        if enable_progress_tracking:
            self.progress_tracker = ProgressTracker()
        else:
            self.progress_tracker = None
    
    def execute_mapping_import(self,
                             mapping_id: int,
                             csv_sources: Dict[str, Any],
                             strategy: str = "auto",
                             **kwargs) -> ImportResult:
        """
        Execute complete mapping-driven import workflow.
        
        Args:
            mapping_id: ID of the mapping to execute
            csv_sources: Dictionary mapping dataset names to CSV data
            strategy: Processing strategy ("auto", "entity_centric", "streaming", "multi_phase")
            **kwargs: Additional execution parameters
            
        Returns:
            ImportResult with execution details and results
        """
        start_time = datetime.now(timezone.utc)
        
        # Initialize result
        result = ImportResult(
            success=True,
            mapping_id=mapping_id,
            mapping_name="Unknown",
            organization="Unknown",
            strategy_used=strategy,
            execution_time_seconds=0.0,
            start_time=start_time,
            end_time=start_time,
            datasets_processed=0
        )
        
        try:
            logger.info(f"Starting mapping-driven import for mapping {mapping_id}")
            
            # Phase 1: Load and validate mapping
            execution_config = self._load_and_validate_mapping(mapping_id, result)
            if not result.success:
                return result
            
            # Phase 2: Choose processing strategy
            optimal_strategy = self._choose_processing_strategy(execution_config, csv_sources, strategy, result)
            
            # Phase 3: Execute import with chosen strategy
            self._execute_import_with_strategy(execution_config, csv_sources, optimal_strategy, result, **kwargs)
            
        except Exception as e:
            logger.error(f"Import orchestration failed: {e}", exc_info=True)
            result.add_error(f"Orchestration failed: {str(e)}")
            
        finally:
            # Finalize result
            result.end_time = datetime.now(timezone.utc)
            result.execution_time_seconds = (result.end_time - result.start_time).total_seconds()
            
            # Calculate performance metrics
            if result.total_rows_processed > 0 and result.execution_time_seconds > 0:
                result.average_rows_per_second = result.total_rows_processed / result.execution_time_seconds
            
            logger.info(f"Import completed: {result.get_summary()}")
        
        return result
    
    def _load_and_validate_mapping(self, mapping_id: int, result: ImportResult) -> Optional[ExecutionConfig]:
        """Load and validate mapping configuration"""
        
        try:
            # Get mapping info
            mapping_info = self.mapping_adapter.get_mapping_info(mapping_id)
            result.mapping_name = mapping_info.name
            result.organization = mapping_info.organization
            
            logger.info(f"Loading mapping '{mapping_info.name}' (ID: {mapping_id})")
            
            # Validate mapping
            validation_result = self.mapping_adapter.validate_mapping(mapping_id)
            if not validation_result.is_valid:
                for error in validation_result.errors:
                    result.add_error(f"Mapping validation: {error}")
                return None
            
            # Add warnings
            for warning in validation_result.warnings:
                result.add_warning(f"Mapping validation: {warning}")
            
            # Translate to execution config
            execution_config = self.mapping_adapter.translate_to_execution_config(mapping_id)
            
            logger.info(f"Mapping loaded: {len(execution_config.datasets)} datasets, "
                       f"{len(execution_config.column_configurations)} columns")
            
            return execution_config
            
        except Exception as e:
            logger.error(f"Failed to load mapping {mapping_id}: {e}")
            result.add_error(f"Failed to load mapping: {str(e)}")
            return None
    
    def _choose_processing_strategy(self, 
                                  execution_config: ExecutionConfig,
                                  csv_sources: Dict[str, Any],
                                  requested_strategy: str,
                                  result: ImportResult) -> ProcessingStrategy:
        """Choose optimal processing strategy"""
        
        try:
            if requested_strategy == "auto":
                strategy = self.strategy_selector.choose_optimal_strategy(execution_config, csv_sources)
                logger.info(f"Auto-selected processing strategy: {strategy.value}")
            else:
                try:
                    strategy = ProcessingStrategy(requested_strategy)
                    logger.info(f"Using requested processing strategy: {strategy.value}")
                except ValueError:
                    logger.warning(f"Unknown strategy '{requested_strategy}', falling back to auto-selection")
                    strategy = self.strategy_selector.choose_optimal_strategy(execution_config, csv_sources)
            
            result.strategy_used = strategy.value
            
            # Log strategy rationale
            rationale = self.strategy_selector.get_strategy_rationale(execution_config, csv_sources, strategy)
            logger.info(f"Strategy rationale: {rationale}")
            
            return strategy
            
        except Exception as e:
            logger.error(f"Failed to choose processing strategy: {e}")
            result.add_warning(f"Strategy selection failed, using streaming_entity_centric: {str(e)}")
            result.strategy_used = "streaming_entity_centric"
            return ProcessingStrategy.STREAMING_ENTITY_CENTRIC
    
    def _execute_import_with_strategy(self,
                                    execution_config: ExecutionConfig,
                                    csv_sources: Dict[str, Any],
                                    strategy: ProcessingStrategy,
                                    result: ImportResult,
                                    **kwargs):
        """Execute import with chosen strategy"""
        
        try:
            # Initialize progress tracking
            if self.progress_tracker:
                self.progress_tracker.start_import(
                    mapping_id=execution_config.mapping_id,
                    total_datasets=len(execution_config.datasets),
                    strategy=strategy.value
                )
            
            # Execute based on strategy
            if strategy == ProcessingStrategy.STREAMING_ENTITY_CENTRIC:
                self._execute_streaming_entity_centric(execution_config, csv_sources, result, **kwargs)
            elif strategy == ProcessingStrategy.MULTI_PHASE:
                self._execute_multi_phase(execution_config, csv_sources, result, **kwargs)
            else:
                raise ValueError(f"Unsupported processing strategy: {strategy}")
            
            # Finalize progress tracking
            if self.progress_tracker:
                self.progress_tracker.complete_import(success=result.success)
                
        except Exception as e:
            logger.error(f"Import execution failed: {e}", exc_info=True)
            result.add_error(f"Execution failed: {str(e)}")
            
            if self.progress_tracker:
                self.progress_tracker.complete_import(success=False, error=str(e))
    
    def _execute_streaming_entity_centric(self,
                                        execution_config: ExecutionConfig,
                                        csv_sources: Dict[str, Any],
                                        result: ImportResult,
                                        **kwargs):
        """Execute using streaming entity-centric processing with chunked data handling"""
        
        logger.info("Executing streaming entity-centric processing with chunked data handling")
        
        try:
            from ..execution.chunked_processor import ChunkedProcessor, StreamingConfig
            
            # Configure streaming parameters
            chunk_size = kwargs.get('chunk_size', 10000)
            max_memory_mb = kwargs.get('max_memory_mb', 200)
            
            streaming_config = StreamingConfig(
                chunk_size=chunk_size,
                max_memory_mb=max_memory_mb,
                enable_gc=True,
                persist_chunks=True
            )
            
            # Initialize chunked processor
            chunked_processor = ChunkedProcessor(
                institution=self.institution,
                base_uri=self.base_uri,
                streaming_config=streaming_config
            )
            
            # Check if we have file paths or in-memory data
            has_large_datasets = self._check_for_large_datasets(csv_sources)
            
            if has_large_datasets:
                # Use chunked processing for large datasets
                logger.info(f"Processing {len(csv_sources)} datasets with chunking (chunk_size={chunk_size}, max_memory={max_memory_mb}MB)")
                
                # Update progress tracking
                if self.progress_tracker:
                    self.progress_tracker.update_progress(
                        phase="streaming_processing",
                        message=f"Starting chunked processing with {chunk_size} rows per chunk"
                    )
                
                # Process with chunked processor
                metrics = chunked_processor.process_large_csv_sources(
                    execution_config, 
                    csv_sources,
                    ProcessingStrategy.STREAMING_ENTITY_CENTRIC
                )
                
                # Get processing summary
                summary = chunked_processor.get_processing_summary()
                
                # Update result with chunked processing metrics
                result.total_resources_created += metrics.resources_created
                result.total_triples_created += metrics.triples_created
                result.total_rows_processed += metrics.rows_processed
                result.total_cells_processed += metrics.cells_processed
                result.datasets_processed = len(execution_config.datasets)
                
                # Add chunked processing details to result
                result.phase_results.append({
                    'phase_name': 'streaming_entity_centric',
                    'chunks_processed': summary['chunks_processed'],
                    'average_memory_usage_mb': summary['average_memory_usage_mb'],
                    'processing_rate_rows_per_second': summary['rows_per_second'],
                    'chunk_details': summary['chunk_details'][:5]  # First 5 chunks for summary
                })
                
                # Estimate peak memory usage
                if summary['chunk_details']:
                    result.peak_memory_usage_mb = max(chunk['memory_mb'] for chunk in summary['chunk_details'])
                
                logger.info(f"Streaming processing completed: {summary['chunks_processed']} chunks, "
                          f"{summary['total_rows_processed']} rows, "
                          f"{summary['average_memory_usage_mb']:.1f}MB avg memory")
                
            else:
                # For smaller datasets, still use chunked processing but with smaller chunks
                logger.info("Datasets are small enough for in-memory processing, using smaller chunks")
                result.add_warning("Datasets small enough for in-memory processing, using smaller chunks")
                # Continue with chunked processing using smaller chunk sizes
                chunk_size = 1000
                
        except ImportError as e:
            logger.error(f"Chunked processor not available: {e}")
            result.add_error(f"Streaming processing failed: chunked processor not available")
            raise ImportError("STREAMING_ENTITY_CENTRIC is the only supported strategy. Chunked processor is required.")
            
        except Exception as e:
            logger.error(f"Streaming entity-centric processing failed: {e}", exc_info=True)
            result.add_error(f"Streaming processing failed: {str(e)}")
            raise Exception(f"STREAMING_ENTITY_CENTRIC processing failed: {str(e)}")
    
    def _execute_multi_phase(self,
                           execution_config: ExecutionConfig,
                           csv_sources: Dict[str, Any],
                           result: ImportResult,
                           **kwargs):
        """Execute using multi-phase processing"""
        
        logger.info("Executing multi-phase processing")
        
        # Use dependency resolver to get processing phases
        from ..mapping_consumer import DependencyResolver
        dependency_resolver = DependencyResolver()
        phases = dependency_resolver.resolve_dependencies(execution_config)
        
        logger.info(f"Processing {len(phases)} phases")
        
        # Initialize execution engine
        engine = MappingExecutionEngine(
            institution=self.institution,
            base_uri=self.base_uri
        )
        
        # Execute each phase
        for phase in phases:
            try:
                logger.info(f"Executing {phase.phase_name}: {phase.datasets}")
                
                phase_start_time = time.time()
                phase_result = {
                    'phase_number': phase.phase_number,
                    'phase_name': phase.phase_name,
                    'datasets': phase.datasets,
                    'resources_created': 0,
                    'triples_created': 0,
                    'rows_processed': 0,
                    'execution_time': 0,
                    'success': True,
                    'errors': []
                }
                
                # Process datasets in this phase
                for dataset_name in phase.datasets:
                    if dataset_name not in csv_sources:
                        result.add_warning(f"No CSV data provided for dataset: {dataset_name}")
                        continue
                    
                    try:
                        # Update progress
                        if self.progress_tracker:
                            self.progress_tracker.start_dataset(dataset_name)
                        
                        # Execute simple import
                        stats = engine.execute_simple_import(
                            csv_data=csv_sources[dataset_name],
                            dataset_name=dataset_name,
                            **kwargs
                        )
                        
                        # Aggregate phase results
                        phase_result['resources_created'] += stats.resources_created
                        phase_result['triples_created'] += stats.triples_created
                        phase_result['rows_processed'] += stats.rows_processed
                        
                        # Aggregate total results
                        result.total_resources_created += stats.resources_created
                        result.total_triples_created += stats.triples_created
                        result.total_rows_processed += stats.rows_processed
                        result.total_cells_processed += stats.cells_processed
                        result.datasets_processed += 1
                        
                        # Store dataset result
                        result.dataset_results[dataset_name] = {
                            'phase': phase.phase_number,
                            'resources_created': stats.resources_created,
                            'triples_created': stats.triples_created,
                            'rows_processed': stats.rows_processed,
                            'cells_processed': stats.cells_processed
                        }
                        
                        # Update progress
                        if self.progress_tracker:
                            self.progress_tracker.complete_dataset(dataset_name, success=True)
                        
                    except Exception as e:
                        logger.error(f"Failed to process dataset {dataset_name} in phase {phase.phase_number}: {e}")
                        phase_result['success'] = False
                        phase_result['errors'].append(f"{dataset_name}: {str(e)}")
                        result.add_error(f"Phase {phase.phase_number}, Dataset {dataset_name}: {str(e)}")
                        
                        if self.progress_tracker:
                            self.progress_tracker.complete_dataset(dataset_name, success=False, error=str(e))
                
                # Finalize phase
                phase_result['execution_time'] = time.time() - phase_start_time
                result.phase_results.append(phase_result)
                
                logger.info(f"Phase {phase.phase_number} completed in {phase_result['execution_time']:.1f}s")
                
            except Exception as e:
                logger.error(f"Phase {phase.phase_number} failed: {e}")
                result.add_error(f"Phase {phase.phase_number}: {str(e)}")
    
    def get_import_status(self, mapping_id: int) -> Optional[Dict[str, Any]]:
        """
        Get current import status for a mapping.
        
        Args:
            mapping_id: ID of the mapping
            
        Returns:
            Status dictionary or None if no active import
        """
        if not self.progress_tracker:
            return None
        
        return self.progress_tracker.get_status(mapping_id)
    
    def analyze_import_feasibility(self,
                                 mapping_id: int,
                                 csv_sources: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze import feasibility without executing.
        
        Args:
            mapping_id: ID of the mapping to analyze
            csv_sources: CSV data sources
            
        Returns:
            Feasibility analysis
        """
        try:
            # Load mapping
            execution_config = self.mapping_adapter.translate_to_execution_config(mapping_id)
            
            # Analyze strategy options
            strategy_analysis = self.strategy_selector.analyze_all_strategies(execution_config, csv_sources)
            
            # Get dependency analysis
            from ..mapping_consumer import DependencyResolver
            dependency_resolver = DependencyResolver()
            dependency_analysis = dependency_resolver.analyze_dependencies(execution_config)
            
            # Estimate resource requirements
            total_rows = 0
            total_columns = 0
            
            for dataset_name, csv_data in csv_sources.items():
                if isinstance(csv_data, list):
                    total_rows += len(csv_data)
                    if csv_data:
                        total_columns += len(csv_data[0])
            
            estimated_resources = total_rows * total_columns
            estimated_memory_mb = estimated_resources * 0.001  # Rough estimate
            
            return {
                'mapping_info': {
                    'id': execution_config.mapping_id,
                    'name': execution_config.mapping_name,
                    'datasets': len(execution_config.datasets),
                    'columns': len(execution_config.column_configurations),
                    'fk_relationships': len(execution_config.fk_relationships)
                },
                'data_analysis': {
                    'total_rows': total_rows,
                    'total_columns': total_columns,
                    'estimated_resources': estimated_resources,
                    'estimated_memory_mb': estimated_memory_mb
                },
                'strategy_analysis': strategy_analysis,
                'dependency_analysis': dependency_analysis,
                'feasibility': 'high' if estimated_memory_mb < 100 else 'medium' if estimated_memory_mb < 500 else 'low',
                'recommendations': self._generate_feasibility_recommendations(strategy_analysis, dependency_analysis, estimated_memory_mb)
            }
            
        except Exception as e:
            logger.error(f"Feasibility analysis failed: {e}")
            return {
                'error': str(e),
                'feasibility': 'unknown'
            }
    
    def _generate_feasibility_recommendations(self,
                                            strategy_analysis: Dict[str, Any],
                                            dependency_analysis: Dict[str, Any],
                                            estimated_memory_mb: float) -> List[str]:
        """Generate feasibility recommendations"""
        
        recommendations = []
        
        # Memory recommendations
        if estimated_memory_mb > 500:
            recommendations.append("Consider using multi-phase processing for large dataset")
            recommendations.append("Monitor memory usage during execution")
        elif estimated_memory_mb > 100:
            recommendations.append("Streaming entity-centric processing recommended")
        
        # Dependency recommendations
        if dependency_analysis.get('has_cycles'):
            recommendations.append("Circular dependencies detected - manual review recommended")
        elif dependency_analysis.get('complexity_assessment') == 'high':
            recommendations.append("Complex dependencies - consider multi-phase processing")
        
        # Strategy recommendations
        recommended_strategy = strategy_analysis.get('recommended_strategy')
        if recommended_strategy:
            recommendations.append(f"Recommended processing strategy: {recommended_strategy}")
        
        return recommendations
    
    def _check_for_large_datasets(self, csv_sources: Dict[str, Any]) -> bool:
        """
        Check if any datasets are large enough to benefit from chunked processing.
        
        Args:
            csv_sources: CSV data sources (file paths or in-memory data)
            
        Returns:
            True if chunked processing is recommended
        """
        for dataset_name, csv_source in csv_sources.items():
            if isinstance(csv_source, str):
                # File path - check file size
                try:
                    import os
                    file_size_mb = os.path.getsize(csv_source) / (1024 * 1024)
                    logger.info(f"Dataset '{dataset_name}' file size: {file_size_mb:.1f}MB")
                    
                    # Consider chunking for files > 50MB
                    if file_size_mb > 50:
                        logger.info(f"Dataset '{dataset_name}' is large ({file_size_mb:.1f}MB), using chunked processing")
                        return True
                        
                except Exception as e:
                    logger.warning(f"Could not determine file size for {csv_source}: {e}")
                    # Assume it's large if we can't determine size
                    return True
                    
            elif isinstance(csv_source, list):
                # In-memory data - check row count
                row_count = len(csv_source)
                logger.info(f"Dataset '{dataset_name}' has {row_count} rows in memory")
                
                # Consider chunking for > 20,000 rows
                if row_count > 20000:
                    logger.info(f"Dataset '{dataset_name}' has many rows ({row_count}), using chunked processing")
                    return True
        
        return False