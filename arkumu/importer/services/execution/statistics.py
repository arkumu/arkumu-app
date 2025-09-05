"""
Statistics and metrics tracking for execution engine.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

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
    
    # FK processing
    fk_relationships_created: int = 0
    fk_dependencies_resolved: int = 0
    cross_dataset_links: int = 0
    
    # External ontology
    external_ontology_lookups: int = 0
    external_ontology_matches: int = 0
    
    # Multi-value processing
    multi_value_cells_split: int = 0
    multi_value_items_created: int = 0
    
    # Entity processing
    entities_processed: int = 0
    properties_created: int = 0
    stub_entities_created: int = 0
    relationships_created: int = 0
    
    # Dataset processing
    datasets_skipped: int = 0
    
    # Efficiency tracking (new metrics for constraint violation prevention)
    resources_attempted: int = 0  # Total resource creation attempts
    resources_filtered: int = 0   # Resources filtered out as duplicates
    triples_attempted: int = 0    # Total triple creation attempts  
    triples_filtered: int = 0     # Triples filtered out as duplicates
    
    # Batch processing metrics
    batch_operations: int = 0     # Number of batch operations performed
    avg_batch_size: float = 0.0   # Average batch size
    
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
        
        # FK processing
        self.fk_relationships_created += other.fk_relationships_created
        self.fk_dependencies_resolved += other.fk_dependencies_resolved
        self.cross_dataset_links += other.cross_dataset_links
        
        # External ontology
        self.external_ontology_lookups += other.external_ontology_lookups
        self.external_ontology_matches += other.external_ontology_matches
        
        # Multi-value
        self.multi_value_cells_split += other.multi_value_cells_split
        self.multi_value_items_created += other.multi_value_items_created
        
        # Entity processing
        self.entities_processed += other.entities_processed
        self.properties_created += other.properties_created
        self.stub_entities_created += other.stub_entities_created
        self.relationships_created += other.relationships_created
        
        # Dataset processing
        self.datasets_skipped += other.datasets_skipped
        
        # Efficiency tracking
        self.resources_attempted += other.resources_attempted
        self.resources_filtered += other.resources_filtered
        self.triples_attempted += other.triples_attempted
        self.triples_filtered += other.triples_filtered
        
        # Batch processing metrics
        self.batch_operations += other.batch_operations
        # Average batch size is recalculated, not summed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'duration_seconds': self.duration_seconds(),
            'rows_processed': self.rows_processed,
            'cells_processed': self.cells_processed,
            'columns_processed': self.columns_processed,
            'resources_created': self.resources_created,
            'resources_updated': self.resources_updated,
            'resources_skipped': self.resources_skipped,
            'triples_created': self.triples_created,
            'values_truncated': self.values_truncated,
            'errors': self.errors,
            'warnings': self.warnings,
            'fk_relationships_created': self.fk_relationships_created,
            'external_ontology_matches': self.external_ontology_matches,
            'multi_value_items_created': self.multi_value_items_created,
            'entities_processed': self.entities_processed,
            'properties_created': self.properties_created,
            'stub_entities_created': self.stub_entities_created,
            'relationships_created': self.relationships_created,
            'datasets_skipped': self.datasets_skipped,
            'resources_attempted': self.resources_attempted,
            'resources_filtered': self.resources_filtered,
            'triples_attempted': self.triples_attempted,
            'triples_filtered': self.triples_filtered,
            'batch_operations': self.batch_operations,
            'avg_batch_size': self.avg_batch_size
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
    
    def log_final_summary(self) -> None:
        """Log a final summary of the execution."""
        summary = self.get_summary()
        overall = summary['overall']
        
        logger.info("=== EXECUTION SUMMARY ===")
        logger.info(f"Duration: {overall['duration_seconds']:.2f}s")
        logger.info(f"Datasets processed: {summary['totals']['total_datasets']}")
        if overall['datasets_skipped'] > 0:
            logger.info(f"Datasets skipped: {overall['datasets_skipped']}")
        logger.info(f"Rows: {overall['rows_processed']}, Cells: {overall['cells_processed']}")
        logger.info(f"Resources: {overall['resources_created']} created, {overall['resources_updated']} updated")
        
        # Efficiency metrics
        if overall.get('resources_attempted', 0) > 0:
            efficiency = (overall['resources_created'] / overall['resources_attempted']) * 100
            logger.info(f"Resource efficiency: {efficiency:.1f}% ({overall['resources_created']}/{overall['resources_attempted']})")
            if overall.get('resources_filtered', 0) > 0:
                logger.info(f"Resources filtered (duplicates): {overall['resources_filtered']}")
        
        if overall.get('triples_attempted', 0) > 0:
            triple_efficiency = (overall['triples_created'] / overall['triples_attempted']) * 100
            logger.info(f"Triple efficiency: {triple_efficiency:.1f}% ({overall['triples_created']}/{overall['triples_attempted']})")
            if overall.get('triples_filtered', 0) > 0:
                logger.info(f"Triples filtered (duplicates): {overall['triples_filtered']}")
        
        if overall.get('batch_operations', 0) > 0:
            logger.info(f"Batch operations: {overall['batch_operations']}, avg size: {overall.get('avg_batch_size', 0):.1f}")
        
        logger.info(f"FK relationships: {overall['fk_relationships_created']}")
        logger.info(f"External ontology matches: {overall['external_ontology_matches']}")
        if overall['errors'] > 0:
            logger.warning(f"Errors: {overall['errors']}")
        if overall['warnings'] > 0:
            logger.info(f"Warnings: {overall['warnings']}")
        logger.info("========================") 