"""
Statistics and metrics tracking for execution engine.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from arkumu.importer.utils.mapping_utils import MappingUtils

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """Detailed metrics for a single execution."""
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Data processing
    rows_processed: int = 0
    cells_processed: int = 0
    columns_processed: int = 0
    
    # Resource operations
    resources_created: int = 0
    resources_updated: int = 0
    resources_skipped: int = 0
    
    # Triple operations
    triples_created: int = 0
    triples_updated: int = 0
    
    # Values (legacy - kept for truncation tracking)
    values_truncated: int = 0
    
    # Errors
    errors: int = 0
    warnings: int = 0
    
    # FK processing - ENHANCED DETAIL
    fk_relationships_created: int = 0
    fk_dependencies_resolved: int = 0
    cross_dataset_links: int = 0
    fk_relationships_queued: int = 0      # Total FK relationships queued for resolution
    fk_relationships_resolved: int = 0     # Successfully resolved FKs
    fk_relationships_failed: int = 0       # Failed FK resolutions
    fk_orphaned_references: int = 0        # FKs pointing to missing datasets
    fk_stub_entities_created: int = 0      # Stub entities created for missing FK targets
    fk_stub_entities_resolved: int = 0     # Stub entities resolved to real entities
    fk_missing_source_entities: int = 0    # FKs with missing source entities
    fk_multi_value_relationships: int = 0  # Multi-value FK relationships
    fk_unique_source_entities: int = 0     # Number of unique source entities with FKs
    fk_target_datasets: Dict[str, int] = field(default_factory=dict)  # FK count by target dataset
    
    # Relationship Context (Junction Tables) - NEW SECTION
    junction_entities_created: int = 0
    junction_primary_links: int = 0
    junction_secondary_links: int = 0
    junction_context_attributes: int = 0
    junction_missing_fks: int = 0
    junction_contexts_processed: Dict[str, int] = field(default_factory=dict)  # Count by context ID
    
    # External ontology
    external_ontology_lookups: int = 0
    external_ontology_matches: int = 0
    
    # Multi-value processing - ENHANCED DETAIL
    multi_value_cells_split: int = 0
    multi_value_items_created: int = 0
    multi_value_columns_processed: int = 0
    multi_value_max_items_per_cell: int = 0
    multi_value_avg_items_per_cell: float = 0.0
    multi_value_columns_detail: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Details per column
    
    # Column Type Distribution - NEW SECTION
    column_types: Dict[str, int] = field(default_factory=dict)  # Count by column type
    anchor_columns_processed: int = 0
    regular_columns_processed: int = 0
    fk_columns_processed: int = 0
    external_ontology_columns_processed: int = 0
    
    # Entity processing
    entities_processed: int = 0
    properties_created: int = 0
    stub_entities_created: int = 0
    relationships_created: int = 0
    
    # Dataset processing
    datasets_skipped: int = 0
    datasets_processed: int = 0
    empty_datasets: int = 0
    
    # Efficiency tracking (new metrics for constraint violation prevention)
    resources_attempted: int = 0  # Total resource creation attempts
    resources_filtered: int = 0   # Resources filtered out as duplicates
    triples_attempted: int = 0    # Total triple creation attempts  
    triples_filtered: int = 0     # Triples filtered out as duplicates
    constraint_violations_prevented: int = 0  # Total prevented violations
    
    # Batch processing metrics
    batch_operations: int = 0     # Number of batch operations performed
    avg_batch_size: float = 0.0   # Average batch size
    
    # Performance metrics - NEW SECTION
    cache_hits: int = 0
    cache_misses: int = 0
    database_queries: int = 0
    bulk_operations: int = 0
    
    def duration_seconds(self) -> float:
        """Calculate execution duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    def merge(self, other: 'ExecutionMetrics') -> None:
        """Merge another metrics object into this one."""
        # Data processing
        self.rows_processed += other.rows_processed
        self.cells_processed += other.cells_processed
        self.columns_processed += other.columns_processed
        
        # Resource operations
        self.resources_created += other.resources_created
        self.resources_updated += other.resources_updated
        self.resources_skipped += other.resources_skipped
        
        # Triple operations  
        self.triples_created += other.triples_created
        self.triples_updated += other.triples_updated
        
        # Values
        self.values_truncated += other.values_truncated
        
        # Errors
        self.errors += other.errors
        self.warnings += other.warnings
        
        # FK processing - ENHANCED
        self.fk_relationships_created += other.fk_relationships_created
        self.fk_dependencies_resolved += other.fk_dependencies_resolved
        self.cross_dataset_links += other.cross_dataset_links
        self.fk_relationships_queued += other.fk_relationships_queued
        self.fk_relationships_resolved += other.fk_relationships_resolved
        self.fk_relationships_failed += other.fk_relationships_failed
        self.fk_orphaned_references += other.fk_orphaned_references
        self.fk_stub_entities_created += other.fk_stub_entities_created
        self.fk_missing_source_entities += other.fk_missing_source_entities
        self.fk_multi_value_relationships += other.fk_multi_value_relationships
        self.fk_unique_source_entities += other.fk_unique_source_entities
        
        # Merge FK target datasets dict
        for dataset, count in other.fk_target_datasets.items():
            self.fk_target_datasets[dataset] = self.fk_target_datasets.get(dataset, 0) + count
        
        # Junction tables
        self.junction_entities_created += other.junction_entities_created
        self.junction_primary_links += other.junction_primary_links
        self.junction_secondary_links += other.junction_secondary_links
        self.junction_context_attributes += other.junction_context_attributes
        self.junction_missing_fks += other.junction_missing_fks
        
        # Merge junction contexts dict
        for context_id, count in other.junction_contexts_processed.items():
            self.junction_contexts_processed[context_id] = self.junction_contexts_processed.get(context_id, 0) + count
        
        # External ontology
        self.external_ontology_lookups += other.external_ontology_lookups
        self.external_ontology_matches += other.external_ontology_matches
        
        # Multi-value - ENHANCED
        self.multi_value_cells_split += other.multi_value_cells_split
        self.multi_value_items_created += other.multi_value_items_created
        self.multi_value_columns_processed += other.multi_value_columns_processed
        self.multi_value_max_items_per_cell = max(self.multi_value_max_items_per_cell, other.multi_value_max_items_per_cell)
        
        # Merge multi-value column details
        for col_name, details in other.multi_value_columns_detail.items():
            if col_name not in self.multi_value_columns_detail:
                self.multi_value_columns_detail[col_name] = details
            else:
                # Merge column statistics
                self.multi_value_columns_detail[col_name]['cells_split'] += details.get('cells_split', 0)
                self.multi_value_columns_detail[col_name]['items_created'] += details.get('items_created', 0)
        
        # Column types
        for col_type, count in other.column_types.items():
            self.column_types[col_type] = self.column_types.get(col_type, 0) + count
        self.anchor_columns_processed += other.anchor_columns_processed
        self.regular_columns_processed += other.regular_columns_processed
        self.fk_columns_processed += other.fk_columns_processed
        self.external_ontology_columns_processed += other.external_ontology_columns_processed
        
        # Entity processing
        self.entities_processed += other.entities_processed
        self.properties_created += other.properties_created
        self.stub_entities_created += other.stub_entities_created
        self.relationships_created += other.relationships_created
        
        # Dataset processing
        self.datasets_skipped += other.datasets_skipped
        self.datasets_processed += other.datasets_processed
        self.empty_datasets += other.empty_datasets
        
        # Efficiency tracking
        self.resources_attempted += other.resources_attempted
        self.resources_filtered += other.resources_filtered
        self.triples_attempted += other.triples_attempted
        self.triples_filtered += other.triples_filtered
        self.constraint_violations_prevented += other.constraint_violations_prevented
        
        # Batch processing metrics
        self.batch_operations += other.batch_operations
        # Average batch size is recalculated, not summed
        
        # Performance metrics
        self.cache_hits += other.cache_hits
        self.cache_misses += other.cache_misses
        self.database_queries += other.database_queries
        self.bulk_operations += other.bulk_operations
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            # Timing
            'duration_seconds': self.duration_seconds(),
            
            # Core processing
            'rows_processed': self.rows_processed,
            'cells_processed': self.cells_processed,
            'columns_processed': self.columns_processed,
            
            # Resources and triples
            'resources_created': self.resources_created,
            'resources_updated': self.resources_updated,
            'resources_skipped': self.resources_skipped,
            'triples_created': self.triples_created,
            'values_truncated': self.values_truncated,
            
            # FK relationships - DETAILED
            'fk_relationships': {
                'queued': self.fk_relationships_queued,
                'resolved': self.fk_relationships_resolved,
                'failed': self.fk_relationships_failed,
                'orphaned': self.fk_orphaned_references,
                'stub_entities_created': self.fk_stub_entities_created,
                'missing_source_entities': self.fk_missing_source_entities,
                'multi_value_relationships': self.fk_multi_value_relationships,
                'unique_source_entities': self.fk_unique_source_entities,
                'by_target_dataset': self.fk_target_datasets,
                'total_created': self.fk_relationships_created
            },
            
            # Junction tables (relationship contexts)
            'junction_tables': {
                'entities_created': self.junction_entities_created,
                'primary_links': self.junction_primary_links,
                'secondary_links': self.junction_secondary_links,
                'context_attributes': self.junction_context_attributes,
                'missing_fks': self.junction_missing_fks,
                'by_context': self.junction_contexts_processed
            },
            
            # Multi-value columns - DETAILED
            'multi_value_columns': {
                'cells_split': self.multi_value_cells_split,
                'items_created': self.multi_value_items_created,
                'columns_processed': self.multi_value_columns_processed,
                'max_items_per_cell': self.multi_value_max_items_per_cell,
                'avg_items_per_cell': self.multi_value_avg_items_per_cell,
                'by_column': self.multi_value_columns_detail
            },
            
            # Column type distribution
            'column_distribution': {
                'by_type': self.column_types,
                'anchor': self.anchor_columns_processed,
                'regular': self.regular_columns_processed,
                'foreign_key': self.fk_columns_processed,
                'external_ontology': self.external_ontology_columns_processed
            },
            
            # External ontology
            'external_ontology': {
                'lookups': self.external_ontology_lookups,
                'matches': self.external_ontology_matches
            },
            
            # Entity processing
            'entities': {
                'processed': self.entities_processed,
                'properties_created': self.properties_created,
                'stub_entities': self.stub_entities_created,
                'relationships_created': self.relationships_created
            },
            
            # Dataset summary
            'datasets': {
                'processed': self.datasets_processed,
                'skipped': self.datasets_skipped,
                'empty': self.empty_datasets
            },
            
            # Efficiency metrics
            'efficiency': {
                'resources_attempted': self.resources_attempted,
                'resources_filtered': self.resources_filtered,
                'triples_attempted': self.triples_attempted,
                'triples_filtered': self.triples_filtered,
                'constraint_violations_prevented': self.constraint_violations_prevented,
                'resource_efficiency_pct': (self.resources_created / self.resources_attempted * 100) if self.resources_attempted > 0 else 100,
                'triple_efficiency_pct': (self.triples_created / self.triples_attempted * 100) if self.triples_attempted > 0 else 100
            },
            
            # Batch and performance
            'performance': {
                'batch_operations': self.batch_operations,
                'avg_batch_size': self.avg_batch_size,
                'cache_hits': self.cache_hits,
                'cache_misses': self.cache_misses,
                'cache_hit_rate_pct': (self.cache_hits / (self.cache_hits + self.cache_misses) * 100) if (self.cache_hits + self.cache_misses) > 0 else 0,
                'database_queries': self.database_queries,
                'bulk_operations': self.bulk_operations
            },
            
            # Errors and warnings
            'errors': self.errors,
            'warnings': self.warnings
        }


class ExecutionStatistics:
    """Statistics tracker for execution operations."""
    
    def __init__(self):
        self.current_metrics = ExecutionMetrics()
        self.dataset_metrics: Dict[str, ExecutionMetrics] = {}
        
    def start_execution(self) -> None:
        """Mark the start of execution."""
        self.current_metrics.start_time = datetime.now(timezone.utc)
        logger.info("Execution statistics tracking started")
    
    def end_execution(self) -> None:
        """Mark the end of execution."""
        self.current_metrics.end_time = datetime.now(timezone.utc)
        duration = self.current_metrics.duration_seconds()
        logger.info(f"Execution completed in {duration:.2f} seconds")
    
    def start_dataset(self, dataset_name: str) -> None:
        """Start tracking a specific dataset."""
        if dataset_name not in self.dataset_metrics:
            self.dataset_metrics[dataset_name] = ExecutionMetrics()
        self.dataset_metrics[dataset_name].start_time = datetime.now(timezone.utc)
    
    def end_dataset(self, dataset_name: str) -> None:
        """End tracking a specific dataset."""
        if dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].end_time = datetime.now(timezone.utc)
    
    def increment_resources_created(self, count: int = 1, dataset_name: Optional[str] = None) -> None:
        """Increment resource creation count."""
        self.current_metrics.resources_created += count
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].resources_created += count
    
    def increment_fk_relationships(self, count: int = 1, dataset_name: Optional[str] = None) -> None:
        """Increment FK relationship count."""
        self.current_metrics.fk_relationships_created += count
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].fk_relationships_created += count
    
    def increment_external_ontology_matches(self, count: int = 1, dataset_name: Optional[str] = None) -> None:
        """Increment external ontology match count."""
        self.current_metrics.external_ontology_matches += count
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].external_ontology_matches += count
    
    def add_error(self, message: str, dataset_name: Optional[str] = None) -> None:
        """Add an error to the statistics."""
        self.current_metrics.errors += 1
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].errors += 1
        logger.error(f"Execution error: {message}")
    
    def add_warning(self, message: str, dataset_name: Optional[str] = None) -> None:
        """Add a warning to the statistics."""
        self.current_metrics.warnings += 1
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].warnings += 1
        logger.warning(f"Execution warning: {message}")
    
    def increment_datasets_skipped(self, count: int = 1) -> None:
        """Increment skipped datasets count."""
        self.current_metrics.datasets_skipped += count
    
    def track_fk_relationship_queued(self, target_dataset: str, is_multi_value: bool = False, dataset_name: Optional[str] = None) -> None:
        """Track FK relationship queued for resolution."""
        self.current_metrics.fk_relationships_queued += 1
        if is_multi_value:
            self.current_metrics.fk_multi_value_relationships += 1
        # Track by target dataset
        self.current_metrics.fk_target_datasets[target_dataset] = self.current_metrics.fk_target_datasets.get(target_dataset, 0) + 1
        
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].fk_relationships_queued += 1
            if is_multi_value:
                self.dataset_metrics[dataset_name].fk_multi_value_relationships += 1
    
    def track_fk_relationships_queued(self, count: int, dataset_name: Optional[str] = None) -> None:
        """Track multiple FK relationships queued for resolution."""
        self.current_metrics.fk_relationships_queued += count
        
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].fk_relationships_queued += count
    
    def track_fk_resolution_result(self, resolved: int, failed: int, orphaned: int, stub_created: int, missing_source: int, unique_sources: int) -> None:
        """Track FK resolution results."""
        self.current_metrics.fk_relationships_resolved += resolved
        self.current_metrics.fk_relationships_failed += failed
        self.current_metrics.fk_orphaned_references += orphaned
        self.current_metrics.fk_stub_entities_created += stub_created
        self.current_metrics.fk_missing_source_entities += missing_source
        self.current_metrics.fk_unique_source_entities = unique_sources
    
    def track_junction_entity(self, context_id: str, primary_linked: bool, secondary_linked: bool, attributes_count: int) -> None:
        """Track junction entity creation."""
        self.current_metrics.junction_entities_created += 1
        self.current_metrics.junction_contexts_processed[context_id] = self.current_metrics.junction_contexts_processed.get(context_id, 0) + 1
        
        if primary_linked:
            self.current_metrics.junction_primary_links += 1
        if secondary_linked:
            self.current_metrics.junction_secondary_links += 1
        
        self.current_metrics.junction_context_attributes += attributes_count
    
    def track_junction_missing_fk(self, count: int = 1) -> None:
        """Track missing FK in junction table."""
        self.current_metrics.junction_missing_fks += count
    
    def track_multi_value_column(self, column_name: str, cells_split: int, items_created: int, max_items: int) -> None:
        """Track multi-value column processing."""
        self.current_metrics.multi_value_columns_processed += 1
        self.current_metrics.multi_value_cells_split += cells_split
        self.current_metrics.multi_value_items_created += items_created
        self.current_metrics.multi_value_max_items_per_cell = max(self.current_metrics.multi_value_max_items_per_cell, max_items)
        
        # Update average
        if self.current_metrics.multi_value_cells_split > 0:
            self.current_metrics.multi_value_avg_items_per_cell = self.current_metrics.multi_value_items_created / self.current_metrics.multi_value_cells_split
        
        # Track per-column details
        if column_name not in self.current_metrics.multi_value_columns_detail:
            self.current_metrics.multi_value_columns_detail[column_name] = {
                'cells_split': 0,
                'items_created': 0,
                'max_items': 0
            }
        
        self.current_metrics.multi_value_columns_detail[column_name]['cells_split'] += cells_split
        self.current_metrics.multi_value_columns_detail[column_name]['items_created'] += items_created
        self.current_metrics.multi_value_columns_detail[column_name]['max_items'] = max(
            self.current_metrics.multi_value_columns_detail[column_name]['max_items'],
            max_items
        )
    
    def track_column_type(self, column_type: str, dataset_name: Optional[str] = None) -> None:
        """Track column type processing."""
        self.current_metrics.column_types[column_type] = self.current_metrics.column_types.get(column_type, 0) + 1
        
        if column_type == 'anchor':
            self.current_metrics.anchor_columns_processed += 1
        elif column_type == 'regular':
            self.current_metrics.regular_columns_processed += 1
        elif column_type == 'foreign_key':
            self.current_metrics.fk_columns_processed += 1
        elif column_type == 'multi_value':
            self.current_metrics.multi_value_columns_processed += 1
        elif column_type == 'multi_value_foreign_key':
            self.current_metrics.fk_columns_processed += 1
            self.current_metrics.multi_value_columns_processed += 1
            self.current_metrics.fk_multi_value_relationships += 1
        elif column_type == 'external_ontology':
            self.current_metrics.external_ontology_columns_processed += 1
        
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].column_types[column_type] = self.dataset_metrics[dataset_name].column_types.get(column_type, 0) + 1
    
    def track_cache_access(self, hit: bool = True) -> None:
        """Track cache hit/miss."""
        if hit:
            self.current_metrics.cache_hits += 1
        else:
            self.current_metrics.cache_misses += 1
    
    def track_database_query(self, count: int = 1) -> None:
        """Track database queries."""
        self.current_metrics.database_queries += count
    
    def track_bulk_operation(self, count: int = 1) -> None:
        """Track bulk database operations."""
        self.current_metrics.bulk_operations += count
    
    def track_dataset_processed(self, is_empty: bool = False) -> None:
        """Track dataset processing."""
        self.current_metrics.datasets_processed += 1
        if is_empty:
            self.current_metrics.empty_datasets += 1
    
    def track_constraint_violations_prevented(self, count: int) -> None:
        """Track prevented constraint violations."""
        self.current_metrics.constraint_violations_prevented += count
    
    def track_resource_filtering(self, attempted: int, actual_created: int, dataset_name: Optional[str] = None) -> None:
        """Track resource creation efficiency (attempted vs actual)."""
        filtered = attempted - actual_created
        self.current_metrics.resources_attempted += attempted
        self.current_metrics.resources_filtered += filtered
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].resources_attempted += attempted
            self.dataset_metrics[dataset_name].resources_filtered += filtered
    
    def track_triple_filtering(self, attempted: int, actual_created: int, dataset_name: Optional[str] = None) -> None:
        """Track triple creation efficiency (attempted vs actual)."""
        filtered = attempted - actual_created
        self.current_metrics.triples_attempted += attempted
        self.current_metrics.triples_filtered += filtered
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].triples_attempted += attempted
            self.dataset_metrics[dataset_name].triples_filtered += filtered
    
    def track_batch_operation(self, batch_size: int, dataset_name: Optional[str] = None) -> None:
        """Track batch processing operations."""
        self.current_metrics.batch_operations += 1
        # Update running average of batch sizes
        total_items = (self.current_metrics.avg_batch_size * (self.current_metrics.batch_operations - 1)) + batch_size
        self.current_metrics.avg_batch_size = total_items / self.current_metrics.batch_operations
        
        if dataset_name and dataset_name in self.dataset_metrics:
            self.dataset_metrics[dataset_name].batch_operations += 1
            dataset_total = (self.dataset_metrics[dataset_name].avg_batch_size * 
                           (self.dataset_metrics[dataset_name].batch_operations - 1)) + batch_size
            self.dataset_metrics[dataset_name].avg_batch_size = dataset_total / self.dataset_metrics[dataset_name].batch_operations
    
    def merge_metrics(self, metrics: ExecutionMetrics) -> None:
        """Merge external metrics into current statistics."""
        self.current_metrics.merge(metrics)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all statistics."""
        summary = {
            'overall': self.current_metrics.to_dict(),
            'datasets': {
                name: metrics.to_dict() 
                for name, metrics in self.dataset_metrics.items()
            },
            'totals': {
                'total_datasets': len(self.dataset_metrics),
                'total_duration': self.current_metrics.duration_seconds(),
                'avg_dataset_duration': (
                    sum(m.duration_seconds() for m in self.dataset_metrics.values()) / 
                    len(self.dataset_metrics) if self.dataset_metrics else 0
                )
            }
        }
        return summary
    
    def analyze_mapping_complexity(self, mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze mapping complexity using MappingUtils and combine with execution stats.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict: Combined complexity analysis and execution metrics
        """
        # Get comprehensive mapping analysis
        mapping_analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        complexity_analysis = MappingUtils.calculate_mapping_complexity(mapping_config)
        
        # Combine with execution statistics
        execution_summary = self.get_summary()
        
        return {
            'mapping_structure': mapping_analysis,
            'complexity_score': complexity_analysis,
            'execution_metrics': execution_summary,
            'performance_insights': {
                'complexity_vs_performance': self._calculate_complexity_performance_ratio(
                    complexity_analysis['complexity_score'], 
                    execution_summary['overall']['duration_seconds']
                ),
                'multi_value_fk_processing_efficiency': self._calculate_mv_fk_efficiency(),
                'column_type_distribution_match': self._compare_planned_vs_actual_columns(mapping_analysis)
            }
        }
    
    def _calculate_complexity_performance_ratio(self, complexity_score: int, duration_seconds: float) -> Dict[str, Any]:
        """Calculate performance ratio based on mapping complexity."""
        if duration_seconds == 0:
            return {'ratio': 0, 'rating': 'excellent', 'notes': 'No execution time recorded'}
        
        ratio = complexity_score / duration_seconds if duration_seconds > 0 else 0
        
        if ratio > 50:
            rating = 'excellent'
        elif ratio > 20:
            rating = 'good'
        elif ratio > 10:
            rating = 'average'
        else:
            rating = 'needs_optimization'
            
        return {
            'ratio': ratio,
            'rating': rating,
            'complexity_score': complexity_score,
            'duration_seconds': duration_seconds,
            'notes': f'Processed {complexity_score} complexity points in {duration_seconds:.2f}s'
        }
    
    def _calculate_mv_fk_efficiency(self) -> Dict[str, Any]:
        """Calculate multi-value FK processing efficiency."""
        mv_fk_queued = self.current_metrics.fk_multi_value_relationships
        mv_fk_resolved = getattr(self.current_metrics, 'fk_multi_value_resolved', 0)  # May not exist in older versions
        
        if mv_fk_queued == 0:
            return {'efficiency': 100, 'notes': 'No multi-value FK columns processed'}
        
        efficiency = (mv_fk_resolved / mv_fk_queued * 100) if mv_fk_queued > 0 else 0
        
        return {
            'efficiency_percentage': efficiency,
            'mv_fk_queued': mv_fk_queued,
            'mv_fk_resolved': mv_fk_resolved,
            'notes': f'Multi-value FK efficiency: {efficiency:.1f}%'
        }
    
    def _compare_planned_vs_actual_columns(self, mapping_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Compare planned column types vs actually processed."""
        planned_counts = {
            'regular': mapping_analysis.get('regular_columns', 0),
            'anchor': mapping_analysis.get('anchor_columns', 0),
            'foreign_key': mapping_analysis.get('foreign_key_columns', 0),
            'multi_value': mapping_analysis.get('multi_value_columns', 0),
            'multi_value_fk': mapping_analysis.get('multi_value_fk_columns', 0),
            'external_ontology': mapping_analysis.get('external_ontology_columns', 0),
            'relationship_context': mapping_analysis.get('relationship_context_columns', 0)
        }
        
        actual_counts = {
            'regular': self.current_metrics.regular_columns_processed,
            'anchor': self.current_metrics.anchor_columns_processed,
            'foreign_key': self.current_metrics.fk_columns_processed,
            'multi_value': self.current_metrics.multi_value_columns_processed,
            'multi_value_fk': self.current_metrics.fk_multi_value_relationships,
            'external_ontology': self.current_metrics.external_ontology_columns_processed,
            'relationship_context': 0  # May need to be tracked separately
        }
        
        mismatches = []
        for col_type in planned_counts:
            planned = planned_counts[col_type]
            actual = actual_counts[col_type]
            if planned != actual:
                mismatches.append({
                    'column_type': col_type,
                    'planned': planned,
                    'actual': actual,
                    'difference': actual - planned
                })
        
        return {
            'planned_counts': planned_counts,
            'actual_counts': actual_counts,
            'mismatches': mismatches,
            'accuracy': len([t for t in planned_counts if planned_counts[t] == actual_counts[t]]) / len(planned_counts) * 100
        }
    
    def log_final_summary(self) -> None:
        """Log a final summary of the execution."""
        summary = self.get_summary()
        overall = summary['overall']
        
        logger.info("\n" + "="*80)
        logger.info("                        IMPORT EXECUTION SUMMARY")
        logger.info("="*80)
        
        # Basic metrics
        logger.info(f"\n📊 CORE METRICS:")
        logger.info(f"  Duration: {overall['duration_seconds']:.2f}s")
        logger.info(f"  Datasets: {overall['datasets']['processed']} processed, {overall['datasets']['skipped']} skipped, {overall['datasets']['empty']} empty")
        logger.info(f"  Rows: {overall['rows_processed']:,}")
        logger.info(f"  Cells: {overall['cells_processed']:,}")
        logger.info(f"  Entities: {overall['entities']['processed']:,}")
        
        # Resource creation
        logger.info(f"\n🔧 RESOURCE CREATION:")
        logger.info(f"  Resources: {overall['resources_created']:,} created")
        logger.info(f"  Triples: {overall['triples_created']:,} created")
        logger.info(f"  Properties: {overall['entities']['properties_created']:,} created")
        
        # Efficiency metrics
        logger.info(f"\n⚡ EFFICIENCY METRICS:")
        logger.info(f"  Resource efficiency: {overall['efficiency']['resource_efficiency_pct']:.1f}%")
        logger.info(f"  Triple efficiency: {overall['efficiency']['triple_efficiency_pct']:.1f}%")
        logger.info(f"  Duplicates prevented: {overall['efficiency']['resources_filtered'] + overall['efficiency']['triples_filtered']:,}")
        logger.info(f"  Constraint violations prevented: {overall['efficiency']['constraint_violations_prevented']:,}")
        
        # FK Relationships - DETAILED
        fk_data = overall['fk_relationships']
        logger.info(f"\n🔗 FOREIGN KEY RELATIONSHIPS:")
        logger.info(f"  Total queued: {fk_data['queued']:,}")
        logger.info(f"  Successfully resolved: {fk_data['resolved']:,} ({(fk_data['resolved']/fk_data['queued']*100) if fk_data['queued'] > 0 else 0:.1f}%)")
        logger.info(f"  Failed resolutions: {fk_data['failed']:,}")
        logger.info(f"  Orphaned references: {fk_data['orphaned']:,}")
        logger.info(f"  Stub entities created: {fk_data['stub_entities_created']:,}")
        logger.info(f"  Multi-value FKs: {fk_data['multi_value_relationships']:,}")
        logger.info(f"  Unique source entities with FKs: {fk_data['unique_source_entities']:,}")
        
        if fk_data['by_target_dataset']:
            logger.info(f"\n  FK Distribution by Target Dataset:")
            for dataset, count in sorted(fk_data['by_target_dataset'].items(), key=lambda x: x[1], reverse=True)[:10]:
                logger.info(f"    • {dataset}: {count:,}")
        
        # Junction Tables (Relationship Contexts)
        junction_data = overall['junction_tables']
        if junction_data['entities_created'] > 0:
            logger.info(f"\n🔄 JUNCTION TABLES (Relationship Contexts):")
            logger.info(f"  Junction entities: {junction_data['entities_created']:,}")
            logger.info(f"  Primary links: {junction_data['primary_links']:,}")
            logger.info(f"  Secondary links: {junction_data['secondary_links']:,}")
            logger.info(f"  Context attributes: {junction_data['context_attributes']:,}")
            if junction_data['missing_fks'] > 0:
                logger.info(f"  Missing FK references: {junction_data['missing_fks']:,}")
            
            if junction_data['by_context']:
                logger.info(f"\n  Junction Table Distribution:")
                for context_id, count in junction_data['by_context'].items():
                    logger.info(f"    • {context_id}: {count:,} entities")
        
        # Multi-value Columns - DETAILED
        mv_data = overall['multi_value_columns']
        if mv_data['cells_split'] > 0:
            logger.info(f"\n🔀 MULTI-VALUE COLUMNS:")
            logger.info(f"  Columns processed: {mv_data['columns_processed']}")
            logger.info(f"  Cells split: {mv_data['cells_split']:,}")
            logger.info(f"  Items created: {mv_data['items_created']:,}")
            logger.info(f"  Max items per cell: {mv_data['max_items_per_cell']}")
            if mv_data['avg_items_per_cell'] > 0:
                logger.info(f"  Avg items per cell: {mv_data['avg_items_per_cell']:.2f}")
            
            if mv_data['by_column']:
                logger.info(f"\n  Multi-value Column Details:")
                for col_name, details in sorted(mv_data['by_column'].items()):
                    logger.info(f"    • {col_name}: {details.get('cells_split', 0)} cells → {details.get('items_created', 0)} items")
        
        # Column Distribution
        col_dist = overall['column_distribution']
        logger.info(f"\n📋 COLUMN TYPE DISTRIBUTION:")
        logger.info(f"  Regular columns: {col_dist['regular']}")
        logger.info(f"  Anchor columns: {col_dist['anchor']}")
        logger.info(f"  Foreign key columns: {col_dist['foreign_key']}")
        logger.info(f"  External ontology columns: {col_dist['external_ontology']}")
        
        # Performance metrics
        perf_data = overall['performance']
        logger.info(f"\n🚀 PERFORMANCE METRICS:")
        logger.info(f"  Batch operations: {perf_data['batch_operations']:,}")
        logger.info(f"  Avg batch size: {perf_data['avg_batch_size']:.1f}")
        logger.info(f"  Cache hit rate: {perf_data['cache_hit_rate_pct']:.1f}%")
        logger.info(f"  Database queries: {perf_data['database_queries']:,}")
        logger.info(f"  Bulk operations: {perf_data['bulk_operations']:,}")
        
        # Errors and warnings
        if overall['errors'] > 0 or overall['warnings'] > 0:
            logger.info(f"\n⚠️  ISSUES:")
            if overall['errors'] > 0:
                logger.warning(f"  Errors: {overall['errors']}")
            if overall['warnings'] > 0:
                logger.info(f"  Warnings: {overall['warnings']}")
        
        logger.info("\n" + "="*80)
        logger.info("                        END OF IMPORT SUMMARY")
        logger.info("="*80 + "\n") 