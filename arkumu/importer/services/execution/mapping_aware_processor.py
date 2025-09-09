"""
Mapping-Aware Processor

Enhanced processor that consumes mapping configurations and handles
complex column types including FK relationships, external ontologies,
and multi-value columns.
"""

import logging
from typing import Dict, Any, List, Optional, Union, Tuple, Set
from dataclasses import dataclass
from datetime import datetime
import polars as pl
import hashlib
from django.core.cache import cache

from arkumu.importer.services.mapping_consumer import ExecutionConfig, ColumnConfig, FKRelationship as MappingFKRelationship, ProcessingStrategy
from .data_processor import DataProcessor
from .resource_manager import ResourceManager
from arkumu.metadata.models.resource import ResourceType, Resource
from .statistics import ExecutionStatistics, ExecutionMetrics
from arkumu.common.enums import UpdateStrategy
from arkumu.metadata.services.mapping import FKConfig as BulkFKRelationship
from arkumu.importer.utils.progress import publish_progress
from arkumu.importer.utils.mapping_utils import MappingUtils

logger = logging.getLogger(__name__)


@dataclass
class ProcessingContext:
    """Context for mapping-aware processing"""
    execution_config: ExecutionConfig
    current_dataset: str
    all_csv_sources: Dict[str, Any]
    entity_cache: Dict[str, Any]  # Cache for FK resolution
    processed_datasets: Set[str]  # Track which datasets have been processed
    log_details: bool = False  # Control detailed logging
    blueprints: Optional[Dict[str, Any]] = None  # Schema blueprints for enhanced processing


class MappingAwareProcessor:
    """
    Enhanced processor that handles mapping configurations.
    
    Supports all column types from the GUI mapping system including:
    - Anchor columns (custom primary keys)
    - Foreign key relationships (cross-dataset)
    - Multi-value columns (comma-separated values)
    - Relationship contexts (junction table attributes)
    - External ontology integration (ORCID, Wikidata, etc.)
    """
    
    def __init__(self,
                 organization=None,
                 statistics: ExecutionStatistics = None,
                 institution: Optional[str] = None,
                 base_uri: str = "",
                 ingest_session = None,
                 channel_id: Optional[str] = None):
        """
        Initialize mapping-aware processor.
        
        Args:
            organization: Organization object for ownership tracking
            base_uri: Base URI for resource generation
            statistics: Statistics tracker
            ingest_session: IngestSession instance for progress tracking
            channel_id: SSE channel ID for progress updates
        """
        # Support both old signature (organization, base_uri, ...) and tests passing institution directly
        self.organization = organization
        self.institution = institution or (organization.code if organization else "default")
        self.base_uri = base_uri
        self.statistics = statistics
        self.channel_id = channel_id
        self.session = ingest_session
        self.total_records = 0
        self.processed_records = 0
        
        # Initialize component processors
        self.data_processor = DataProcessor()
        self.resource_manager = ResourceManager(
            organization=organization,
            base_uri=base_uri,
            statistics=statistics
        )
        
        # No longer using execution engine - simplified to streaming entity-centric only
        
        # Processing state
        self.entity_cache = {}
        self.pending_relationships = []
        
        # Enhanced FK relationship debugging removed - using built-in debug logging
        
        # Schema-first blueprint tracking
        self.dataset_blueprints = {}
    
    def _update_progress(self, message: str, percentage: Optional[int] = None):
        """Send progress update via SSE and update model."""
        if not self.channel_id or not self.session:
            return
        
        if percentage is None:
            percentage = int((self.processed_records / self.total_records) * 100) if self.total_records > 0 else 0
        
        payload = {
            'message': message,
            'percentage': percentage,
            'processed': self.processed_records,
            'total': self.total_records,
        }
        
        publish_progress(self.channel_id, payload)
        
        # Update model
        self.session.progress_percentage = percentage
        self.session.progress_message = message
        self.session.save(update_fields=['progress_percentage', 'progress_message'])
    
    def process_with_execution_config(self,
                                    execution_config: ExecutionConfig,
                                    csv_sources: Dict[str, Any],
                                    strategy: ProcessingStrategy) -> ExecutionMetrics:
        """
        Process datasets using execution configuration.
        
        Args:
            execution_config: Execution configuration for processing
            csv_sources: Dictionary mapping dataset names to CSV data
            strategy: Processing strategy to use
            
        Returns:
            Aggregated execution metrics
        """
        logger.info(f"Starting mapping-aware processing with {strategy} strategy")
        
        # Initialize progress
        self._update_progress("Initializing import...", 0)
        
        # Create processing context
        context = ProcessingContext(
            execution_config=execution_config,
            current_dataset="",
            all_csv_sources=csv_sources,
            entity_cache={},
            processed_datasets=set()
        )
        
        # Phase 1: Create complete schema blueprints FIRST (if not already loaded)
        if not self.dataset_blueprints:
            logger.info("📋 Creating schema blueprints (none loaded)")
            self._create_complete_schema_blueprints(execution_config)
        else:
            logger.info(f"📋 Using existing schema blueprints ({len(self.dataset_blueprints)} datasets)")
        
        # Execute with streaming entity-centric strategy (only supported strategy)
        return self._process_streaming_entity_centric(context)
    
    def _process_streaming_entity_centric(self, context: ProcessingContext) -> ExecutionMetrics:
        """Process using streaming entity-centric approach"""
        
        logger.info("Processing with streaming entity-centric strategy")
        
        # For now, use chunked processing with smaller batches
        chunk_size = 1000
        
        # FIXED: Only process datasets that are actually present in CSV sources
        # This prevents false warnings about missing datasets that aren't being processed
        try:
            for dataset_name in context.all_csv_sources.keys():
                # Find the corresponding dataset configuration (with consistent URI slugification)
                from arkumu.common.uri_utils import slugify_uri_part
                
                dataset_config = None
                slugified_csv_name = slugify_uri_part(dataset_name)
                for config in context.execution_config.datasets:
                    if slugify_uri_part(config.dataset_name) == slugified_csv_name:
                        dataset_config = config
                        break
                
                if not dataset_config:
                    # Log available configurations for debugging
                    available_configs = [config.dataset_name for config in context.execution_config.datasets]
                    logger.warning(f"CSV data provided for '{dataset_name}' (slugified: '{slugified_csv_name}') but no mapping configuration found. Available: {available_configs}")
                    continue
                
                logger.info(f"🔍 PROCESSING: Dataset '{dataset_name}' (has CSV data)")
                logger.info(f"📊 Available csv_sources: {list(context.all_csv_sources.keys())}")
                
                context.current_dataset = dataset_config.dataset_name
                csv_data = context.all_csv_sources[dataset_name]
                
                # Convert to DataFrame for chunked processing
                # Handle the test data format: {'headers': [...], 'rows': [...]}
                if isinstance(csv_data, dict) and 'rows' in csv_data:
                    df = self.data_processor.ensure_dataframe(csv_data['rows'])
                else:
                    df = self.data_processor.ensure_dataframe(csv_data)
                
                # Check if dataset is empty
                total_rows = df.height
                if total_rows == 0:
                    logger.warning(f"Dataset {dataset_config.dataset_name} is empty, creating dataset resource with schema metadata")
                    self.statistics.increment_datasets_skipped()
                    
                    # IMPORTANT: Still create the dataset resource even for empty datasets
                    # This ensures the dataset URI exists in the graph
                    dataset_resource = self.resource_manager.create_dataset_resource(dataset_config.dataset_name)
                    logger.info(f"Created dataset resource for empty dataset '{dataset_config.dataset_name}'")
                    
                    # IMPORTANT: Create schema metadata triples for empty datasets
                    # This ensures the dataset is properly connected to its column structure from the mapping
                    self._create_schema_metadata_for_empty_dataset(dataset_config, dataset_resource, context)
                    
                    # Check for orphaned FK references pointing to this empty dataset
                    self._check_orphaned_fk_references(dataset_config.dataset_name, context)
                    context.processed_datasets.add(dataset_config.dataset_name)
                    continue
                
                # Track all entities for this dataset across all chunks
                dataset_entities = []
                dataset_name = dataset_config.dataset_name
            
            # Create dataset resource once for the entire dataset
            dataset_resource = self.resource_manager.create_dataset_resource(dataset_name)
            
            # Process in chunks
            logger.info(f"🚀 Starting entity processing for {dataset_name}: {total_rows} rows in chunks of {chunk_size}")
            
            for chunk_start in range(0, total_rows, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_rows)
                chunk_df = df[chunk_start:chunk_end]
                
                # Convert chunk back to list format
                chunk_data = chunk_df.to_dicts()
                
                # Log chunk progress
                chunk_num = (chunk_start // chunk_size) + 1
                total_chunks = (total_rows + chunk_size - 1) // chunk_size
                logger.info(f"⚡ Processing chunk {chunk_num}/{total_chunks} for {dataset_name}: rows {chunk_start + 1}-{chunk_end}")
                
                # Process entities in this chunk and collect them
                chunk_entities = self._process_dataset_chunk_with_entities(dataset_config, chunk_data, context)
                dataset_entities.extend(chunk_entities)
                
                logger.info(f"✅ Chunk {chunk_num}/{total_chunks} completed: {len(chunk_entities)} entities created ({len(dataset_entities)} total)")
            
                # Create dataset-entity linking triples for ALL entities in the dataset
                logger.info(f"Creating dataset-entity links for {dataset_name} ({len(dataset_entities)} entities)")
                if dataset_entities:
                    dataset_entity_triples = self.resource_manager.create_dataset_entity_links_bulk(
                        dataset_entities, dataset_resource
                    )
                    logger.info(f"Created {len(dataset_entity_triples)} dataset-entity linking triples for {dataset_name}")
                    try:
                        self.statistics.current_metrics.triples_created += len(dataset_entity_triples)
                        self.statistics.current_metrics.relationships_created += len(dataset_entity_triples)
                    except Exception:
                        pass

                context.processed_datasets.add(dataset_config.dataset_name)
        finally:
            # Always attempt to resolve queued FK relationships even if some datasets errored
            logger.info("FK resolve: starting")
            try:
                self._resolve_pending_relationships(context)
            finally:
                logger.info("FK resolve: finished")
        
        # Log processing summary
        self._log_processing_summary(context)
        
        return self.statistics.current_metrics
    
    def _process_dataset_chunk_with_entities(self,
                                           dataset_config,
                                           csv_data: List[Dict[str, Any]],
                                           context: ProcessingContext) -> List:
        """Process a chunk of dataset and return created entities (for streaming)"""
        
        dataset_name = dataset_config.dataset_name
        logger.debug(f"Processing chunk for dataset: {dataset_name} ({len(csv_data)} rows)")
        
        # Create mapping configuration for multi-value detection
        mapping_config = self._create_mapping_config_from_dataset(dataset_config)
        
        # Prepare data with mapping configuration
        df = self.data_processor.prepare_for_processing(csv_data, mapping_config)
        if df.height == 0:
            return []
        
        # Group columns by type for efficient processing
        column_groups = self._group_columns_by_type(dataset_config.columns)
        
        # Track entities created for this chunk
        chunk_entities = []
        total_chunk_rows = df.height
        
        # Process each row as a complete entity
        logger.debug(f"🔄 Processing {total_chunk_rows} entities in chunk for {dataset_name}")
        
        for row_idx, row_data in enumerate(df.iter_rows(named=True), 1):
            # Log slow processing every 10 entities for detailed debugging
            if row_idx % 10 == 0 and total_chunk_rows > 50:
                logger.debug(f"🐌 Processing entity {row_idx}/{total_chunk_rows} for {dataset_name} (checking for slowdowns)")
            
            entity_uri = self._generate_entity_uri(dataset_name, row_data, dataset_config)
            
            # Create the main entity
            entity_resource = self.resource_manager.create_entity_resource(entity_uri, dataset_name)
            context.entity_cache[entity_uri] = entity_resource
            chunk_entities.append(entity_resource)
            # Metrics: one row processed and one resource created for entity
            try:
                self.statistics.current_metrics.rows_processed += 1
                self.statistics.current_metrics.resources_created += 1
            except Exception:
                pass
            
            # Link entity to its type via rdf:type
            self._create_rdf_type_relationship(entity_resource, dataset_name)
            try:
                # rdf:type is a relationship triple
                self.statistics.current_metrics.relationships_created += 1
                self.statistics.current_metrics.triples_created += 1
            except Exception:
                pass
            
            # Process regular columns
            self._process_regular_columns(entity_resource, row_data, column_groups['regular'], context)
            
            # Process anchor columns
            self._process_anchor_columns(entity_resource, row_data, column_groups['anchor'], context)
            
            # Process multi-value columns
            self._process_multi_value_columns(entity_resource, row_data, column_groups['multi_value'], context)
            
            # Queue FK relationships for later resolution (includes multi-value FKs)
            all_fk_columns = column_groups['foreign_key'] + column_groups['multi_value_foreign_key']
            self._queue_fk_relationships(entity_uri, row_data, all_fk_columns, context)
            
            # Process external ontology columns
            self._process_external_ontology_columns(entity_resource, row_data, column_groups['external_ontology'], context)
            
            # Process relationship context columns (as regular properties)
            self._process_relationship_context_columns(entity_resource, row_data, column_groups['relationship_context'], context)
            
            # Track row processing
            self.statistics.current_metrics.rows_processed += 1
            
            # Log progress every 100 entities within chunk
            if row_idx % 100 == 0:
                logger.info(f"📊 Processed {row_idx}/{total_chunk_rows} entities in current chunk for {dataset_name}")
        
        logger.debug(f"Processed chunk for {dataset_name}: created {len(chunk_entities)} entities")
        return chunk_entities
    
    def _process_dataset_with_entities(self,
                                     dataset_config,
                                     csv_data: List[Dict[str, Any]],
                                     context: ProcessingContext):
        """Process a dataset with complete entity creation"""
        
        dataset_name = dataset_config.dataset_name
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing dataset: {dataset_name}")
        logger.info(f"Total rows: {len(csv_data)}")
        
        # Create mapping configuration for multi-value detection
        mapping_config = self._create_mapping_config_from_dataset(dataset_config)
        
        # Prepare data with mapping configuration
        df = self.data_processor.prepare_for_processing(csv_data, mapping_config)
        if df.height == 0:
            return
        
        # Create dataset and structural resources
        dataset_resource = self.resource_manager.create_dataset_resource(dataset_name)
        
        # Group columns by type for efficient processing
        column_groups = self._group_columns_by_type(dataset_config.columns)
        
        # Track entities created for this dataset
        dataset_entities = []
        
        # Log column type distribution
        logger.info(f"Column types for {dataset_name}:")
        logger.info(f"  - Regular columns: {len(column_groups['regular'])}")
        logger.info(f"  - Anchor columns: {len(column_groups['anchor'])}")
        logger.info(f"  - Multi-value columns: {len(column_groups['multi_value'])}")
        logger.info(f"  - Foreign key columns: {len(column_groups['foreign_key'])}")
        logger.info(f"  - Multi-value FK columns: {len(column_groups['multi_value_foreign_key'])}")
        logger.info(f"  - External ontology columns: {len(column_groups['external_ontology'])}")
        logger.info(f"  - Relationship context columns: {len(column_groups['relationship_context'])}")
        
        # Process each row as a complete entity
        for row_data in df.iter_rows(named=True):
            entity_uri = self._generate_entity_uri(dataset_name, row_data, dataset_config)
            
            # Create the main entity
            entity_resource = self.resource_manager.create_entity_resource(entity_uri, dataset_name)
            context.entity_cache[entity_uri] = entity_resource
            dataset_entities.append(entity_resource)
            
            # Link entity to its type via rdf:type
            self._create_rdf_type_relationship(entity_resource, dataset_name)
            
            # Process regular columns
            self._process_regular_columns(entity_resource, row_data, column_groups['regular'], context)
            
            # Process anchor columns
            self._process_anchor_columns(entity_resource, row_data, column_groups['anchor'], context)
            
            # Process multi-value columns
            self._process_multi_value_columns(entity_resource, row_data, column_groups['multi_value'], context)
            
            # Queue FK relationships for later resolution (includes multi-value FKs)
            all_fk_columns = column_groups['foreign_key'] + column_groups['multi_value_foreign_key']
            self._queue_fk_relationships(entity_uri, row_data, all_fk_columns, context)
            
            # Process external ontology columns
            self._process_external_ontology_columns(entity_resource, row_data, column_groups['external_ontology'], context)
            
            # Process relationship context columns (as regular properties)
            self._process_relationship_context_columns(entity_resource, row_data, column_groups['relationship_context'], context)
            
            # Track row processing
            self.statistics.current_metrics.rows_processed += 1
        
        # Create entity-dataset linking triples (entity → isPartOf → dataset)
        logger.info(f"Creating dataset-entity links for {dataset_name}")
        if dataset_entities:
            dataset_entity_triples = self.resource_manager.create_dataset_entity_links_bulk(
                dataset_entities, dataset_resource
            )
            logger.info(f"Created {len(dataset_entity_triples)} dataset-entity linking triples")
    
    def _process_entities_only(self,
                             dataset_config,
                             csv_data: List[Dict[str, Any]],
                             context: ProcessingContext):
        """Process entities without relationships (for multi-phase)"""
        
        dataset_name = dataset_config.dataset_name
        logger.info(f"Processing entities only for dataset '{dataset_name}'")
        
        # Create mapping configuration for multi-value detection
        mapping_config = self._create_mapping_config_from_dataset(dataset_config)
        
        # Prepare data with mapping configuration
        df = self.data_processor.prepare_for_processing(csv_data, mapping_config)
        if df.height == 0:
            return
        
        # Create dataset resource
        dataset_resource = self.resource_manager.create_dataset_resource(dataset_name)
        
        # Group columns (exclude FK columns in this phase)
        column_groups = self._group_columns_by_type(dataset_config.columns)
        
        # Process each row (entities only)
        for row_data in df.iter_rows(named=True):
            entity_uri = self._generate_entity_uri(dataset_name, row_data, dataset_config)
            entity_resource = self.resource_manager.create_entity_resource(entity_uri, dataset_name)
            context.entity_cache[entity_uri] = entity_resource
            
            # Link entity to its type via rdf:type
            self._create_rdf_type_relationship(entity_resource, dataset_name)
            
            # Process only non-relationship columns
            self._process_regular_columns(entity_resource, row_data, column_groups['regular'], context)
            self._process_anchor_columns(entity_resource, row_data, column_groups['anchor'], context)
            self._process_multi_value_columns(entity_resource, row_data, column_groups['multi_value'], context)
            self._process_external_ontology_columns(entity_resource, row_data, column_groups['external_ontology'], context)
            self._process_relationship_context_columns(entity_resource, row_data, column_groups['relationship_context'], context)
    
    def _group_columns_by_type(self, columns: List[ColumnConfig]) -> Dict[str, List[ColumnConfig]]:
        """Group columns by their type using centralized column analysis utility"""
        
        # Convert columns to mapping config format for centralized analysis
        mapping_config = {"workspace_columns": {}}
        for column in columns:
            mapping_config["workspace_columns"][column.column_name] = {
                "is_multi_value": column.is_multi_value,
                "is_fk": column.column_type.value == 'foreign_key' or bool(getattr(column, 'fk_config', None)),
                "is_anchor": column.is_anchor,
                "is_external_ontology": column.is_external_ontology,
                "is_relationship_context": column.column_type.value == 'relationship_context',
                "column_name": column.column_name,
                "arkumu_type": column.arkumu_type
            }
        
        # Use centralized analysis from MappingUtils
        analysis_result = MappingUtils.analyze_mapping_structure(mapping_config)
        
        # Use MappingUtils to group columns by type
        column_groups = MappingUtils.group_columns_by_type(mapping_config)
        
        # Convert to the expected format with column objects
        groups = {
            'regular': [],
            'anchor': [],
            'foreign_key': [],
            'multi_value': [],
            'multi_value_foreign_key': [],
            'relationship_context': [],
            'external_ontology': []
        }
        
        # Create lookup for columns by name
        column_lookup = {col.column_name: col for col in columns}
        
        # Map column names to column objects using centralized grouping
        for column_type, column_names in column_groups.items():
            if column_type in groups:
                for col_name in column_names:
                    if col_name in column_lookup:
                        groups[column_type].append(column_lookup[col_name])
                        if column_type == 'multi_value_foreign_key':
                            logger.debug(f"   Column '{col_name}' is multi-value FK - will be processed specially")
        
        return groups
    
    def _generate_entity_uri(self,
                           dataset_name: str,
                           row_data: Dict[str, Any],
                           dataset_config) -> str:
        """Generate URI for an entity based on anchor columns or row ID"""
        
        # Find anchor columns for this dataset
        anchor_columns = [col.column_name for col in dataset_config.columns if col.is_anchor]
        
        if anchor_columns:
            # Use anchor columns to generate URI
            anchor_values = []
            for col_name in anchor_columns:
                value = row_data.get(col_name, '')
                if value:
                    anchor_values.append(str(value).strip())
            
            if anchor_values:
                entity_id = '_'.join(anchor_values)
                return self.resource_manager.generate_entity_uri(dataset_name, entity_id)
        
        # Fall back to row ID
        row_id = row_data.get('row_id', 0)
        display_row_id = int(row_id) + 1 if str(row_id).isdigit() else row_id
        return self.resource_manager.generate_entity_uri(dataset_name, str(display_row_id))
    
    def _process_regular_columns(self,
                               entity_resource,
                               row_data: Dict[str, Any],
                               columns: List[ColumnConfig],
                               context: ProcessingContext):
        """Process regular columns as simple properties with optimized batching"""
        if not columns:
            return
            
        if context.log_details:
            logger.debug(f"Processing {len(columns)} regular columns for entity {entity_resource.uri}")
        
        # Collect all regular column triples for batch creation
        batch_property_data = []
        
        for column in columns:
            value = row_data.get(column.column_name)
            if value is not None and str(value).strip():
                # Create property URI from arkumu_type
                property_uri = self._generate_property_uri(column.arkumu_type)
                
                # Add to batch
                batch_property_data.append((
                    entity_resource,
                    property_uri,
                    str(value).strip()
                ))
        
        # Create all regular column triples in batch if we have any
        if batch_property_data:
            logger.debug(f"Creating {len(batch_property_data)} regular property triples in batch")
            self.resource_manager.create_property_triples_bulk(batch_property_data)
            try:
                self.statistics.current_metrics.triples_created += len(batch_property_data)
            except Exception:
                pass
    
    def _process_anchor_columns(self,
                              entity_resource,
                              row_data: Dict[str, Any],
                              columns: List[ColumnConfig],
                              context: ProcessingContext):
        """Process anchor columns (primary key properties) with optimized batching"""
        if not columns:
            return
            
        logger.debug(f"Processing {len(columns)} anchor columns: {[col.column_name for col in columns]}")
        
        # Collect all anchor column triples for batch creation
        batch_property_data = []
        
        for column in columns:
            value = row_data.get(column.column_name)
            if value is not None and str(value).strip():
                # Create identifier property
                property_uri = self._generate_property_uri(column.arkumu_type)
                
                # Add to batch
                batch_property_data.append((
                    entity_resource,
                    property_uri,
                    str(value).strip()
                ))
        
        # Create all anchor column triples in batch if we have any
        if batch_property_data:
            logger.debug(f"Creating {len(batch_property_data)} anchor property triples in batch")
            self.resource_manager.create_property_triples_bulk(batch_property_data)
            try:
                self.statistics.current_metrics.triples_created += len(batch_property_data)
            except Exception:
                pass
    
    def _process_multi_value_columns(self,
                                   entity_resource,
                                   row_data: Dict[str, Any],
                                   columns: List[ColumnConfig],
                                   context: ProcessingContext):
        """Process multi-value columns (comma-separated values) with optimized batching"""
        if not columns:
            return
            
        logger.debug(f"Processing {len(columns)} multi-value columns: {[col.column_name for col in columns]}")
        
        # Collect all multi-value triples for batch creation
        batch_property_data = []
        
        for column in columns:
            value = row_data.get(column.column_name)
            if not value or not str(value).strip():
                continue
                
            # Split the value using the configured separator
            values = self._split_multi_value(str(value), column.multi_value_separator)
            
            # Generate property URI once for all values in this column
            property_uri = self._generate_property_uri(column.arkumu_type)
            
            # Add each value to the batch
            for single_value in values:
                if single_value.strip():
                    batch_property_data.append((
                        entity_resource,
                        property_uri,
                        single_value.strip()
                    ))
                    # Track multi-value processing statistics
                    self.statistics.current_metrics.multi_value_items_created += 1
        
        # Create all multi-value triples in batch if we have any
        if batch_property_data:
            logger.debug(f"Creating {len(batch_property_data)} multi-value property triples in batch")
            self.resource_manager.create_property_triples_bulk(batch_property_data)
            # Update statistics for multi-value cell processing
            self.statistics.current_metrics.multi_value_cells_split += len(columns)
            try:
                self.statistics.current_metrics.triples_created += len(batch_property_data)
            except Exception:
                pass
    
    def _queue_fk_relationships(self,
                              entity_uri: str,
                              row_data: Dict[str, Any],
                              columns: List[ColumnConfig],
                              context: ProcessingContext):
        """Queue FK relationships for later resolution with comprehensive logging and batching.
        
        This method processes FK columns and queues relationships for batch resolution.
        Each FK relationship links a source entity to one or more target entities in other datasets.
        
        Args:
            entity_uri: URI of the source entity
            row_data: Raw row data containing FK values
            columns: List of FK column configurations
            context: Processing context with entity cache and configuration
        
        FK Resolution Flow:
        1. Extract FK values from row data (handling multi-value columns)
        2. Determine target dataset for each FK column
        3. Group relationships by target dataset for efficient batch processing
        4. Queue relationships for later resolution after all entities are created
        """
        
        if not columns:
            return
            
        if context.log_details:
            logger.debug(f"FK queue: {len(columns)} FK columns for {entity_uri}")
        
        # Group FK relationships by target dataset for better batching
        relationships_by_target = {}
        total_fk_values_processed = 0
        
        for column in columns:
            value = row_data.get(column.column_name)
            if context.log_details:
                logger.debug(f"FK column '{column.column_name}' value='{value}' multi={column.is_multi_value}")
            
            if not value or not str(value).strip():
                logger.debug(f"   ⚠️  FK SKIP: Empty value for column '{column.column_name}'")
                continue
                
            target_dataset = self._get_target_dataset_for_column(column, context)
            if context.log_details:
                logger.debug(f"FK target: {column.column_name} -> {target_dataset}")
            
            # Handle multi-value FKs
            if column.is_multi_value:
                fk_values = self._split_multi_value(str(value), column.multi_value_separator)
                if context.log_details:
                    logger.debug(f"FK multi-value split {len(fk_values)} values")
            else:
                fk_values = [str(value).strip()]
                if context.log_details:
                    logger.debug("FK single-value detected")
            
            # Group by target dataset for more efficient resolution
            if target_dataset not in relationships_by_target:
                relationships_by_target[target_dataset] = []
            
            for fk_idx, fk_value in enumerate(fk_values):
                if fk_value.strip():
                    norm_val = MappingUtils.normalize_fk_value(fk_value)
                    relationship = {
                        'source_entity_uri': entity_uri,
                        'source_column': column.column_name,
                        'target_value': norm_val,
                        'target_dataset': target_dataset,
                        'relationship_type': column.arkumu_type,
                        'is_multi_value': column.is_multi_value,
                        'multi_value_index': fk_idx if column.is_multi_value else None
                    }
                    relationships_by_target[target_dataset].append(relationship)
                    total_fk_values_processed += 1
                    
                    # FK debugging removed for simplicity
                    
                    if context.log_details:
                        logger.debug(f"FK queued: {entity_uri} -[{column.arkumu_type}]→ {target_dataset}.{fk_value.strip()}")
                else:
                    if context.log_details:
                        logger.debug("FK skip: empty value in multi-list")
        
        # Add grouped relationships to pending queue and log statistics
        total_relationships_queued = 0
        for target_dataset, relationships in relationships_by_target.items():
            self.pending_relationships.extend(relationships)
            total_relationships_queued += len(relationships)
            if context.log_details:
                logger.debug(f"FK batch queued {len(relationships)} -> '{target_dataset}'")
        
        logger.info(f"FK queued: {total_relationships_queued} relationships across {len(relationships_by_target)} targets")
        
        # Update statistics
        current_pending_total = len(self.pending_relationships)
        logger.debug(f"   📊 FK QUEUE STATS: Total pending relationships now: {current_pending_total}")
    
    def _process_external_ontology_columns(self,
                                         entity_resource,
                                         row_data: Dict[str, Any],
                                         columns: List[ColumnConfig],
                                         context: ProcessingContext):
        """Process external ontology columns with both soft and hard linking"""
        if columns:
            logger.debug(f"Processing {len(columns)} external ontology columns: {[col.column_name for col in columns]}")
        
        for column in columns:
            value = row_data.get(column.column_name)
            if value is not None and str(value).strip():
                cleaned_value = str(value).strip()
                
                # 1. SOFT LINKING: Create normal property triple (entity -> property -> literal)
                property_uri = self._generate_property_uri(column.arkumu_type)
                triple = self.resource_manager.create_property_triple(
                    entity_resource,
                    property_uri,
                    cleaned_value,
                    "http://www.w3.org/2001/XMLSchema#string"
                )
                try:
                    self.statistics.current_metrics.triples_created += 1
                except Exception:
                    pass
                
                # 2. HARD LINKING: Link external ontology to our literal resource
                external_uri = self._generate_external_ontology_uri(column, cleaned_value)
                
                if external_uri and triple:
                    # Get the literal resource from the triple (object of the triple)
                    literal_resource = triple.object
                    
                    # Create external resource (stub)
                    external_resource = self.resource_manager.create_external_resource(
                        external_uri,
                        column.external_ontology_config.get('ontology_type', 'external')
                    )
                    try:
                        self.statistics.current_metrics.resources_created += 1
                        self.statistics.current_metrics.external_ontology_items_created += 1
                    except Exception:
                        pass
                    
                    # Create owl:sameAs from external ontology to our literal resource
                    self.resource_manager.create_owl_same_as_triple(
                        external_resource,
                        literal_resource
                    )
                    try:
                        self.statistics.current_metrics.triples_created += 1
                        self.statistics.current_metrics.relationships_created += 1
                    except Exception:
                        pass
                    
                    logger.debug(f"Created both soft and hard links for {column.column_name}: "
                               f"entity -> {property_uri} -> '{cleaned_value}' and "
                               f"{external_uri} -> owl:sameAs -> literal_resource('{cleaned_value}')")
    
    def _process_relationship_context_columns(self,
                                            entity_resource,
                                            row_data: Dict[str, Any], 
                                            columns: List[ColumnConfig],
                                            context: ProcessingContext):
        """Process relationship context columns as regular properties"""
        if columns:
            logger.debug(f"Processing {len(columns)} relationship context columns: {[col.column_name for col in columns]}")
        
        for column in columns:
            value = row_data.get(column.column_name)
            if value is not None and str(value).strip():
                cleaned_value = str(value).strip()
                
                # Create property triple (entity -> property -> literal)
                property_uri = self._generate_property_uri(column.arkumu_type)
                self.resource_manager.create_property_triple(
                    entity_resource,
                    property_uri,
                    cleaned_value,
                    "http://www.w3.org/2001/XMLSchema#string"
                )
                
                logger.debug(f"Created relationship context property: entity -> {property_uri} -> '{cleaned_value}'")
    
    def _resolve_pending_relationships(self, context: ProcessingContext):
        """Resolve all pending FK relationships with comprehensive logging and improved batching.
        
        This is the core FK resolution engine that processes queued relationships and creates
        the actual RDF triples linking entities across datasets.
        
        FK Resolution Process:
        1. Group relationships by target dataset for efficient batch processing
        2. For each target dataset batch:
           a. Check if target dataset exists (skip orphaned references)
           b. Pre-create or fetch target entities
           c. Resolve each relationship by creating RDF triples
        3. Log comprehensive statistics and handle failures gracefully
        
        Args:
            context: Processing context containing entity cache and dataset information
        """
        
        if not self.pending_relationships:
            logger.info("🔗 FK RESOLUTION: No pending relationships to resolve")
            return
            
        logger.info(f"\n{'='*60}")
        logger.info(f"🔗 FK RESOLUTION START: Processing {len(self.pending_relationships)} pending FK relationships")
        
        # Group relationships by target dataset for batch processing
        relationships_by_target = self._group_relationships_by_target()
        
        # Log detailed relationship distribution
        logger.info(f"📊 FK RESOLUTION BREAKDOWN: Relationships grouped by target dataset:")
        total_unique_sources = set()
        total_multi_value_relationships = 0
        
        for target_dataset, relationships in relationships_by_target.items():
            sources_in_batch = set(rel['source_entity_uri'] for rel in relationships)
            multi_value_in_batch = sum(1 for rel in relationships if rel.get('is_multi_value', False))
            
            total_unique_sources.update(sources_in_batch)
            total_multi_value_relationships += multi_value_in_batch
            
            logger.info(f"  📦 {target_dataset}: {len(relationships)} relationships from {len(sources_in_batch)} source entities")
            logger.info(f"     🔀 Multi-value relationships: {multi_value_in_batch}")
            
            # Log sample relationship types
            relationship_types = set(rel['relationship_type'] for rel in relationships[:5])
            logger.debug(f"     🏷️  Sample relationship types: {list(relationship_types)}")
        
        logger.info(f"📊 FK RESOLUTION TOTALS: {len(total_unique_sources)} unique source entities, {total_multi_value_relationships} multi-value relationships")
        
        # Process relationships in batches by target dataset
        total_resolved = 0
        total_failed = 0
        total_orphaned = 0
        total_missing_source = 0
        total_stub_created = 0
        
        skipped_datasets = self._identify_skipped_datasets(context)
        
        for target_dataset, relationships in relationships_by_target.items():
            logger.info(f"\n🔄 FK BATCH PROCESSING: {len(relationships)} relationships → '{target_dataset}'")
            
            # Check if target dataset was skipped
            if target_dataset in skipped_datasets:
                if hasattr(context, 'stub_datasets') and target_dataset in context.stub_datasets:
                    logger.info(f"   🏗️  STUB RESOLUTION: Creating stub entities for '{target_dataset}' (has stub structure)")
                else:
                    logger.warning(f"   🚫 ORPHANED BATCH: Skipping relationships to missing dataset '{target_dataset}' (no CSV data)")
                    total_orphaned += len(relationships)
                    
                    # Log detailed orphaned relationship information
                    orphaned_sources = set(rel['source_entity_uri'] for rel in relationships)
                    logger.warning(f"     👻 Orphaned relationships affect {len(orphaned_sources)} source entities")
                    continue
            
            # Process this batch of relationships with detailed logging
            logger.info(f"   ⚡ BATCH START: Resolving {len(relationships)} FK relationships for '{target_dataset}'")
            batch_start_time = datetime.now()
            
            batch_results = self._resolve_relationship_batch(relationships, context)
            
            batch_duration = datetime.now() - batch_start_time
            logger.info(f"   ⏱️  BATCH COMPLETE: {batch_results['resolved']} resolved, {batch_results['failed']} failed, {batch_results['missing_source']} missing source (took {batch_duration.total_seconds():.2f}s)")
            
            total_resolved += batch_results['resolved']
            total_failed += batch_results['failed']
            total_missing_source += batch_results['missing_source']
            total_stub_created += batch_results.get('stub_created', 0)
        
        # Calculate resolution statistics
        total_relationships = len(self.pending_relationships)
        success_rate = (total_resolved / total_relationships * 100) if total_relationships > 0 else 0
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🔗 FK RESOLUTION COMPLETE: Final Statistics")
        logger.info(f"{'='*60}")
        logger.info(f"  ✅ Successfully resolved: {total_resolved} ({success_rate:.1f}%)")
        logger.info(f"  ❌ Resolution failures: {total_failed}")
        logger.info(f"  🔗 Orphaned (missing datasets): {total_orphaned}")
        logger.info(f"  👻 Missing source entities: {total_missing_source}")
        logger.info(f"  🏗️  Stub entities created: {total_stub_created}")
        logger.info(f"  📊 Total relationships processed: {total_relationships}")
        
        # Log performance metrics
        if total_resolved > 0:
            avg_relationships_per_source = total_resolved / len(total_unique_sources) if total_unique_sources else 0
            logger.info(f"  📈 Average FK relationships per entity: {avg_relationships_per_source:.2f}")
        
        # Update statistics and handle warnings
        self.statistics.current_metrics.relationships_created += total_resolved
        
        if total_orphaned > 0:
            self.statistics.add_warning(
                f"Skipped {total_orphaned} FK relationships due to orphaned references to missing/empty datasets"
            )
        
        if total_failed > 0:
            self.statistics.add_warning(
                f"Failed to resolve {total_failed} FK relationships due to missing target entities or other errors"
            )
        
        # Clear pending relationships
        self.pending_relationships = []
        logger.info(f"🧹 FK CLEANUP: Cleared pending relationships queue")
    
    def _process_all_fk_relationships(self, context: ProcessingContext):
        """Process all FK relationships (for multi-phase)"""
        
        logger.info("Processing all FK relationships")
        
        for execution_config in context.execution_config.datasets:
            if execution_config.dataset_name not in context.all_csv_sources:
                continue
            
            csv_data = context.all_csv_sources[execution_config.dataset_name]
            # Create mapping configuration for multi-value detection
            mapping_config = self._create_mapping_config_from_dataset(execution_config)
            df = self.data_processor.prepare_for_processing(csv_data, mapping_config)
            
            # Find FK columns for this dataset
            fk_columns = [col for col in execution_config.columns if col.column_type.value == 'foreign_key']
            
            if not fk_columns:
                continue
            
            # Process FK relationships for each row
            for row_data in df.iter_rows(named=True):
                entity_uri = self._generate_entity_uri(execution_config.dataset_name, row_data, execution_config)
                self._queue_fk_relationships(entity_uri, row_data, fk_columns, context)
        
        # Resolve all relationships
        self._resolve_pending_relationships(context)
    
    def _process_all_relationship_contexts(self, context: ProcessingContext):
        """Process all relationship contexts (junction table attributes)"""
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {len(context.execution_config.relationship_contexts)} relationship contexts (junction tables)")
        
        for rel_context in context.execution_config.relationship_contexts:
            logger.info(f"\nProcessing relationship context: {rel_context.context_id}")
            logger.info(f"  - Dataset: {rel_context.dataset_name}")
            logger.info(f"  - Primary FK: {rel_context.primary_fk} -> {rel_context.primary_entity_type}")
            logger.info(f"  - Secondary FK: {rel_context.secondary_fk} -> {rel_context.secondary_entity_type}")
            logger.info(f"  - Junction attributes: {len(rel_context.junction_attributes)}")
            
            # Find the dataset for this context
            if rel_context.dataset_name not in context.all_csv_sources:
                logger.warning(f"No CSV data for relationship context dataset: {rel_context.dataset_name}")
                continue
            
            csv_data = context.all_csv_sources[rel_context.dataset_name]
            # For relationship contexts, we need to find the dataset config
            dataset_config = next((ds for ds in context.execution_config.datasets 
                                   if ds.dataset_name == rel_context.dataset_name), None)
            mapping_config = self._create_mapping_config_from_dataset(dataset_config) if dataset_config else None
            df = self.data_processor.prepare_for_processing(csv_data, mapping_config)
            
            # Process each row as a junction entity
            for row_data in df.iter_rows(named=True):
                self._process_junction_entity(rel_context, row_data, context)
    
    def _process_junction_entity(self, rel_context, row_data: Dict[str, Any], context: ProcessingContext):
        """Process a single junction entity with relationship context and comprehensive logging.
        
        Junction entities represent many-to-many relationships with additional attributes.
        They connect two entities from different datasets while carrying contextual information.
        
        Relationship Context Flow:
        1. Extract primary and secondary FK values from row data
        2. Generate unique junction entity URI combining both FK values
        3. Create junction entity with its own type and properties
        4. Link junction to both primary and secondary entities via relationships
        5. Add any contextual attributes as properties of the junction entity
        
        Args:
            rel_context: Relationship context configuration
            row_data: Raw CSV row data containing FK values and context attributes
            context: Processing context with entity cache
        """
        
        context_id = rel_context.context_id
        logger.debug(f"🔗 JUNCTION START: Processing junction entity for context '{context_id}'")
        
        # Extract FK values with detailed logging
        primary_value = row_data.get(rel_context.primary_fk, '')
        secondary_value = row_data.get(rel_context.secondary_fk, '')
        
        logger.debug(f"   🔑 PRIMARY FK: '{rel_context.primary_fk}' = '{primary_value}'")
        logger.debug(f"   🔒 SECONDARY FK: '{rel_context.secondary_fk}' = '{secondary_value}'")
        
        if not primary_value or not secondary_value:
            logger.warning(f"   ⚠️  JUNCTION SKIP: Missing FK values for junction entity '{context_id}'")
            logger.warning(f"      Primary FK '{rel_context.primary_fk}': '{primary_value}'")
            logger.warning(f"      Secondary FK '{rel_context.secondary_fk}': '{secondary_value}'")
            return
        
        # Generate unique junction entity URI
        junction_uri = self.resource_manager.generate_junction_uri(
            rel_context.dataset_name,
            str(primary_value),
            str(secondary_value)
        )
        
        logger.debug(f"   🎯 JUNCTION URI: {junction_uri}")
        
        # Create junction entity with specific type
        junction_type = f"{rel_context.dataset_name}_junction"
        junction_entity = self.resource_manager.create_entity_resource(
            junction_uri,
            junction_type
        )
        
        logger.debug(f"   ✅ JUNCTION CREATED: Entity '{junction_uri}' of type '{junction_type}'")
        
        # Link junction entity to its type via rdf:type
        self._create_rdf_type_relationship(junction_entity, junction_type)
        
        # Process contextual attributes with detailed logging
        context_attributes_added = 0
        if hasattr(rel_context, 'context_columns'):
            logger.debug(f"   🏷️  JUNCTION ATTRIBUTES: Processing {len(rel_context.context_columns)} context attributes")
            
            for context_column in rel_context.context_columns:
                value = row_data.get(context_column)
                if value is not None and str(value).strip():
                    property_uri = self._generate_property_uri(f"junction_{context_column}")
                    triple = self.resource_manager.create_property_triple(
                        junction_entity,
                        property_uri,
                        str(value).strip(),
                        "http://www.w3.org/2001/XMLSchema#string"
                    )
                    
                    if triple:
                        context_attributes_added += 1
                        logger.debug(f"     🏷️  ATTRIBUTE: '{context_column}' = '{value}'")
                    else:
                        logger.warning(f"     ❌ ATTRIBUTE FAILED: Could not create attribute '{context_column}'")
                else:
                    logger.debug(f"     ⚠️  ATTRIBUTE SKIP: Empty value for '{context_column}'")
        else:
            logger.debug(f"   🏷️  JUNCTION ATTRIBUTES: No context columns defined")
        
        # Resolve target datasets for FK relationships
        primary_dataset = self._get_target_dataset_from_fk(rel_context.primary_fk, context)
        secondary_dataset = self._get_target_dataset_from_fk(rel_context.secondary_fk, context)
        
        logger.debug(f"   🔗 JUNCTION LINKS: primary → '{primary_dataset}', secondary → '{secondary_dataset}'")
        
        # Create relationships to primary and secondary entities
        primary_entity_uri = self._generate_target_entity_uri(
            primary_dataset,
            str(primary_value),
            context
        )
        
        secondary_entity_uri = self._generate_target_entity_uri(
            secondary_dataset,
            str(secondary_value),
            context
        )
        
        relationships_created = 0
        
        # Link to primary entity
        if primary_entity_uri in context.entity_cache:
            property_uri = self._generate_property_uri("involves_primary")
            primary_triple = self.resource_manager.create_relationship_triple(
                junction_entity,
                property_uri,
                context.entity_cache[primary_entity_uri]
            )
            if primary_triple:
                relationships_created += 1
                logger.debug(f"   🔗 PRIMARY LINK: {junction_uri} -[involves_primary]→ {primary_entity_uri}")
            else:
                logger.warning(f"   ❌ PRIMARY LINK FAILED: Could not link to primary entity")
        else:
            logger.warning(f"   👻 PRIMARY MISSING: Entity {primary_entity_uri} not found in cache")
        
        # Link to secondary entity
        if secondary_entity_uri in context.entity_cache:
            property_uri = self._generate_property_uri("involves_secondary")
            secondary_triple = self.resource_manager.create_relationship_triple(
                junction_entity,
                property_uri,
                context.entity_cache[secondary_entity_uri]
            )
            if secondary_triple:
                relationships_created += 1
                logger.debug(f"   🔗 SECONDARY LINK: {junction_uri} -[involves_secondary]→ {secondary_entity_uri}")
            else:
                logger.warning(f"   ❌ SECONDARY LINK FAILED: Could not link to secondary entity")
        else:
            logger.warning(f"   👻 SECONDARY MISSING: Entity {secondary_entity_uri} not found in cache")
        
        # Log junction entity completion summary
        logger.info(f"   ✅ JUNCTION COMPLETE: Context '{context_id}' → {context_attributes_added} attributes, {relationships_created} relationships")
        
        # Update statistics
        self.statistics.current_metrics.relationships_created += relationships_created
        if context_attributes_added > 0:
            self.statistics.current_metrics.cells_processed += context_attributes_added
    
    # Helper methods
    
    def _split_multi_value(self, value: str, separator: str) -> List[str]:
        """Split multi-value string using separator"""
        if not value or not separator:
            return [value] if value else []
        
        return [v.strip() for v in value.split(separator) if v.strip()]
    
    def _create_schema_metadata_for_empty_dataset(self, dataset_config, dataset_resource, context: ProcessingContext):
        """Create schema metadata triples for empty datasets based on mapping configuration."""
        logger.info(f"   📊 Creating schema metadata for empty dataset '{dataset_config.dataset_name}'")
        
        # 1. Create entity type resource and link to dataset
        entity_columns = [col for col in dataset_config.columns if col.column_type.value == 'entity']
        if entity_columns:
            primary_entity_column = entity_columns[0]
            entity_type_name = primary_entity_column.arkumu_type
        else:
            # Fallback: use dataset name as entity type
            entity_type_name = dataset_config.dataset_name
        
        # Create entity type URI and resource
        entity_type_uri = self._generate_type_uri(entity_type_name)
        
        # Generate clean name for display (same logic as URI generation)
        if entity_type_name.startswith('http://') or entity_type_name.startswith('https://'):
            clean_name = entity_type_name
        else:
            # Remove entity-type- prefix if present (same as URI generation)
            clean_name = entity_type_name.replace('entity-type-', '').replace('entity_type_', '')
        
        entity_type_resource, created = Resource.objects.get_or_create(
            uri=entity_type_uri,
            defaults={
                "resource_type": ResourceType.CLASS,
                "name": clean_name,
                "is_placeholder": False,
                "organization": self.organization
            }
        )
        
        # Link dataset to entity type
        schema_property_uri = self._generate_property_uri("defines_entity_type")
        self.resource_manager.create_relationship_triple(
            dataset_resource,
            schema_property_uri,
            entity_type_resource
        )
        logger.info(f"     🏷️  Linked dataset to entity type '{entity_type_name}'")
        
        # 2. Create property resources for all columns and link to entity type
        property_count = 0
        for column in dataset_config.columns:
            # Generate property URI based on arkumu_type
            property_uri = self._generate_property_uri(column.arkumu_type)
            
            # Create property resource
            property_resource, created = Resource.objects.get_or_create(
                uri=property_uri,
                defaults={
                    "resource_type": ResourceType.PROPERTY,
                    "name": column.arkumu_type,
                    "is_placeholder": False,
                    "organization": self.organization
                }
            )
            
            # Link entity type to property
            property_schema_uri = self._generate_property_uri("defines_property")
            self.resource_manager.create_relationship_triple(
                entity_type_resource,
                property_schema_uri,
                property_resource
            )
            property_count += 1
        
        logger.info(f"     📊 Created schema metadata: 1 entity type, {property_count} properties")
        
        # 3. Add FK relationships from blueprint if they exist
        if hasattr(self, 'dataset_blueprints') and dataset_config.dataset_name in self.dataset_blueprints:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            fk_count = len(blueprint.get('fk_relationships', []))
            if fk_count > 0:
                logger.info(f"     🔗 FK relationships from blueprint: {fk_count}")
        
        logger.info(f"   ✅ Schema metadata created for empty dataset '{dataset_config.dataset_name}'")
    
    def _generate_type_uri(self, type_name: str) -> str:
        """Generate type URI for entity types"""
        # Check if it's already a full URI
        if type_name.startswith('http://') or type_name.startswith('https://'):
            return type_name
        
        # Remove entity-type- prefix if present (redundant in /types/ namespace)
        clean_name = type_name.replace('entity-type-', '').replace('entity_type_', '')
        
        # Use centralized URI generation from common utilities
        from arkumu.common.uri_utils import mint_uri, slugify_uri_part
        safe_type_name = slugify_uri_part(clean_name)
        return mint_uri(self.base_uri, self.institution, "types", safe_type_name)

    def _generate_property_uri(self, arkumu_type: str) -> str:
        """Generate property URI from arkumu_type using centralized URI generation"""
        # Check if it's already a full URI
        if arkumu_type.startswith('http://') or arkumu_type.startswith('https://'):
            return arkumu_type
        
        # Use centralized URI generation from common utilities
        from arkumu.common.uri_utils import mint_uri, slugify_uri_part
        safe_arkumu_type = slugify_uri_part(arkumu_type)
        return mint_uri(self.base_uri, self.institution, "properties", safe_arkumu_type)

    def _create_rdf_type_relationship(self, entity_resource, dataset_name: str):
        """Create rdf:type relationship linking entity to its type from blueprint."""
        if dataset_name in self.dataset_blueprints:
            entity_type_resource = self.dataset_blueprints[dataset_name]['entity_type_resource']
            self.resource_manager.create_relationship_triple(
                entity_resource,
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                entity_type_resource
            )
    
    def _generate_external_ontology_uri(self, column: ColumnConfig, value: str) -> Optional[str]:
        """Generate external ontology URI"""
        if not column.external_ontology_config:
            return None
        
        uri_template = column.external_ontology_config.get('uri_template', '')
        if '{identifier}' in uri_template:
            return uri_template.replace('{identifier}', value)
        
        return None
    
    def _get_target_dataset_for_column(self, column: ColumnConfig, context: ProcessingContext) -> str:
        """Get target dataset for an FK column"""
        # Check if column has direct FK config (it's a dictionary)
        if hasattr(column, 'fk_config') and column.fk_config:
            if isinstance(column.fk_config, dict):
                target_dataset = column.fk_config.get('target_dataset')
            else:
                target_dataset = getattr(column.fk_config, 'target_dataset', None)
            if target_dataset:
                logger.debug(f"✅ Found target dataset from column.fk_config: {target_dataset}")
                return target_dataset
        
        # Look up the target dataset from FK relationships
        for fk_rel in context.execution_config.fk_relationships:
            if fk_rel.source_column == column.column_name:
                logger.debug(f"✅ Found target dataset from execution_config.fk_relationships: {fk_rel.target_dataset}")
                return fk_rel.target_dataset
        
        # Log warning when no FK config found
        logger.warning(f"⚠️ No FK configuration found for column '{column.column_name}'")
        logger.warning(f"   Available FK relationships in config: {[fr.source_column for fr in context.execution_config.fk_relationships]}")
        
        # Fallback to placeholder if not found
        fallback = f"target_dataset_for_{column.column_name}"
        logger.warning(f"   Using fallback target dataset: {fallback}")
        return fallback
    
    def _group_relationships_by_target(self) -> Dict[str, List[Dict]]:
        """Group pending relationships by target dataset for batch processing"""
        relationships_by_target = {}
        
        for relationship in self.pending_relationships:
            target_dataset = relationship['target_dataset']
            if target_dataset not in relationships_by_target:
                relationships_by_target[target_dataset] = []
            relationships_by_target[target_dataset].append(relationship)
        
        return relationships_by_target
    
    def _identify_skipped_datasets(self, context: ProcessingContext) -> Set[str]:
        """Identify datasets that were skipped (no CSV data provided)"""
        skipped_datasets = set()
        for dataset_config in context.execution_config.datasets:
            if dataset_config.dataset_name not in context.all_csv_sources:
                skipped_datasets.add(dataset_config.dataset_name)
        return skipped_datasets
    
    def _resolve_relationship_batch(self, relationships: List[Dict], context: ProcessingContext) -> Dict[str, int]:
        """Resolve a batch of relationships targeting the same dataset with comprehensive logging.
        
        This method processes a batch of FK relationships all targeting the same dataset,
        optimizing performance through batch target entity preparation.
        
        Args:
            relationships: List of relationship dictionaries with source/target information
            context: Processing context containing entity cache
            
        Returns:
            Dictionary with resolution statistics: resolved, failed, missing_source, stub_created
        """
        results = {'resolved': 0, 'failed': 0, 'missing_source': 0, 'stub_created': 0}
        
        if not relationships:
            return results
            
        target_dataset = relationships[0]['target_dataset']
        if context.log_details:
            logger.debug(f"FK prepare targets: {len(relationships)} -> '{target_dataset}'")
        
        # Pre-process target entities for this batch with detailed logging
        target_entities_cache = self._prepare_target_entities_batch(relationships, context)
        
        if context.log_details:
            logger.debug(f"FK cache prepared: {len(target_entities_cache)} targets")
        
        # Track unique source entities and relationship types for statistics
        unique_sources = set()
        relationship_types = set()
        multi_value_count = 0
        
        for i, relationship in enumerate(relationships, 1):
            try:
                source_entity_uri = relationship['source_entity_uri']
                target_value = relationship['target_value']
                relationship_type = relationship['relationship_type']
                is_multi_value = relationship.get('is_multi_value', False)
                multi_value_index = relationship.get('multi_value_index')
                
                unique_sources.add(source_entity_uri)
                relationship_types.add(relationship_type)
                if is_multi_value:
                    multi_value_count += 1
                
                logger.debug(f"    🔗 FK RESOLVE {i}/{len(relationships)}: {source_entity_uri} -[{relationship_type}]→ {target_dataset}.{target_value}")
                if is_multi_value and multi_value_index is not None:
                    logger.debug(f"      🔢 Multi-value index: {multi_value_index}")
                
                # Get source entity from context cache
                source_entity = context.entity_cache.get(source_entity_uri)
                if not source_entity:
                    
                    logger.warning(f"      👻 MISSING SOURCE: Entity {source_entity_uri} not found in cache")
                    results['missing_source'] += 1
                    continue
                
                # Get target entity from batch cache
                target_entity_uri = self._generate_target_entity_uri(
                    relationship['target_dataset'],
                    target_value,
                    context
                )
                
                target_entity = target_entities_cache.get(target_entity_uri)
                if not target_entity:
                    
                    logger.warning(f"      🎯 MISSING TARGET: Could not resolve target entity {target_entity_uri}")
                    results['failed'] += 1
                    continue
                
                # Check if target entity is a stub (was created due to missing CSV data)
                is_stub = getattr(target_entity, 'is_placeholder', False)
                if is_stub:
                    results['stub_created'] += 1
                    logger.debug(f"      🏗️ STUB TARGET: Linking to stub entity {target_entity_uri}")
                
                # Create relationship triple with timing
                resolution_start = datetime.now()
                property_uri = self._generate_property_uri(relationship_type)
                triple = self.resource_manager.create_relationship_triple(
                    source_entity,
                    property_uri,
                    target_entity
                )
                resolution_time_ms = (datetime.now() - resolution_start).total_seconds() * 1000
                
                if triple:
                    results['resolved'] += 1
                    try:
                        self.statistics.current_metrics.relationships_created += 1
                        self.statistics.current_metrics.triples_created += 1
                    except Exception:
                        pass
                    
                    logger.debug(f"      ✅ FK SUCCESS: {source_entity.uri} -[{property_uri}]→ {target_entity.uri}")
                else:
                    
                    logger.error(f"      ❌ FK TRIPLE CREATION FAILED: Could not create triple for relationship")
                    results['failed'] += 1
                
            except Exception as e:
                
                logger.error(f"      💥 FK EXCEPTION: Failed to resolve relationship {i}: {e}")
                logger.debug(f"         Relationship data: {relationship}")
                results['failed'] += 1
        
        # Log batch completion statistics
        success_rate = (results['resolved'] / len(relationships) * 100) if relationships else 0
        
        logger.info(f"FK resolve [{target_dataset}]: queued={len(relationships)} resolved={results['resolved']} failed={results['failed']}")
        if context.log_details:
            logger.debug(f"FK stats: missing_source={results['missing_source']} stubs={results['stub_created']} multi={multi_value_count} unique_sources={len(unique_sources)} types={list(relationship_types)}")
        
        return results
    
    def _prepare_target_entities_batch(self, relationships: List[Dict], context: ProcessingContext) -> Dict[str, Resource]:
        """Pre-create or fetch target entities for a batch of relationships with comprehensive logging.
        
        This optimization method pre-processes all target entities for a batch of relationships
        targeting the same dataset, reducing database queries and improving performance.
        
        Args:
            relationships: List of relationship dictionaries (all targeting same dataset)
            context: Processing context containing entity cache and configuration
            
        Returns:
            Dictionary mapping target entity URIs to Resource objects
        """
        target_entities = {}
        target_dataset = relationships[0]['target_dataset']  # All relationships in batch have same target
        
        # Collect unique target values with frequency analysis
        target_value_frequencies = {}
        for relationship in relationships:
            target_value = relationship['target_value']
            target_value_frequencies[target_value] = target_value_frequencies.get(target_value, 0) + 1
        
        unique_target_values = set(target_value_frequencies.keys())
        logger.debug(f"    🎯 TARGET PREP: Processing {len(unique_target_values)} unique target values for '{target_dataset}'")
        
        # Log target value frequency analysis (helpful for debugging data quality)
        if len(target_value_frequencies) <= 10:
            logger.debug(f"      📊 Target value frequencies: {target_value_frequencies}")
        else:
            # Show top 5 most frequent target values
            top_values = sorted(target_value_frequencies.items(), key=lambda x: x[1], reverse=True)[:5]
            logger.debug(f"      📊 Top 5 target values: {dict(top_values)} (and {len(target_value_frequencies)-5} others)")
        
        # Track preparation statistics
        cache_hits = 0
        cache_misses = 0
        stubs_created = 0
        existing_entities = 0
        
        # Generate target entity URIs and prepare entities
        for target_value in unique_target_values:
            norm_val = MappingUtils.normalize_fk_value(target_value)
            target_entity_uri = self._generate_target_entity_uri(target_dataset, norm_val, context)
            frequency = target_value_frequencies[target_value]
            
            logger.debug(f"      🔍 TARGET: '{target_value}' → {target_entity_uri} (referenced {frequency} times)")
            
            # Check if entity already exists in context cache
            if target_entity_uri in context.entity_cache:
                target_entities[target_entity_uri] = context.entity_cache[target_entity_uri]
                cache_hits += 1
                logger.debug(f"        💾 CACHE HIT: Found in entity cache")
            else:
                cache_misses += 1
                logger.debug(f"        🔍 CACHE MISS: Creating/fetching target entity")
                
                # Create or get target entity (potentially as stub)
                target_entity = self._get_or_create_target_entity(target_entity_uri, {
                    'target_dataset': target_dataset,
                    'target_value': target_value
                }, context)
                
                if target_entity:
                    target_entities[target_entity_uri] = target_entity
                    # Add to context cache for future use
                    context.entity_cache[target_entity_uri] = target_entity
                    
                    # Check if it's a newly created stub
                    if getattr(target_entity, 'is_placeholder', False):
                        stubs_created += 1
                        logger.debug(f"        🏗️ STUB CREATED: New stub entity for missing target")
                    else:
                        existing_entities += 1
                        logger.debug(f"        ✅ EXISTING: Found existing entity in database")
                else:
                    logger.warning(f"        ❌ FAILED: Could not create/fetch target entity {target_entity_uri}")
        
        # Log preparation statistics
        preparation_success_rate = (len(target_entities) / len(unique_target_values) * 100) if unique_target_values else 0
        
        logger.info(f"    📦 TARGET PREP COMPLETE for '{target_dataset}':")
        logger.info(f"      ✅ Prepared: {len(target_entities)}/{len(unique_target_values)} entities ({preparation_success_rate:.1f}%)")
        logger.info(f"      💾 Cache hits: {cache_hits}, misses: {cache_misses}")
        logger.info(f"      🏗️ Stubs created: {stubs_created}")
        logger.info(f"      📁 Existing entities: {existing_entities}")
        
        return target_entities
    
    def _generate_target_entity_uri(self, target_dataset: str, target_value: str, context: ProcessingContext) -> str:
        """Generate URI for target entity"""
        return self.resource_manager.generate_entity_uri(target_dataset, target_value)
    
    def _get_or_create_target_entity(self, target_uri: str, relationship: Dict, context: ProcessingContext):
        """Get existing target entity or create stub with metadata from mapping"""
        # Check cache first
        if target_uri in context.entity_cache:
            logger.debug(f"✅ Found target entity in cache: {target_uri}")
            return context.entity_cache[target_uri]
        
        target_dataset = relationship['target_dataset']
        
        # Try to find if entity was already created in database
        try:
            existing_entity = Resource.objects.get(uri=target_uri, resource_type='IRI')
            logger.debug(f"✅ Found existing target entity in database: {target_uri}")
            context.entity_cache[target_uri] = existing_entity
            return existing_entity
        except Resource.DoesNotExist:
            # Debug: Check if entity exists with different resource type
            all_resources = Resource.objects.filter(uri=target_uri)
            if all_resources.exists():
                logger.warning(f"❌ Target entity exists but wrong type: {target_uri}, types: {[r.resource_type for r in all_resources]}")
            else:
                logger.warning(f"❌ Target entity not found in database: {target_uri}")
                
            # Debug: Check if similar entities exist (for debugging)
            target_value = target_uri.split('/')[-1]
            similar = Resource.objects.filter(
                uri__icontains=target_value,
                resource_type='IRI',
                organization=self.organization
            ).count()
            logger.debug(f"🔍 Similar entities found for '{target_value}': {similar}")
            
            # Debug: Check if target dataset entities exist at all
            dataset_entities = Resource.objects.filter(
                uri__contains=f"/entities/{target_dataset}/",
                resource_type='IRI',
                organization=self.organization
            ).count()
            logger.debug(f"🔍 Total entities in target dataset '{target_dataset}': {dataset_entities}")
            
            pass  # Entity doesn't exist, create stub
        
        # Create stub entity
        logger.error(f"🚨 CRITICAL FK BUG: Creating stub entity for {target_uri} - this should NOT happen if entities are processed correctly!")
        logger.error(f"🚨 This indicates FK resolution is running before target entities are created in dataset: {target_dataset}")
        
        stub_entity = self.resource_manager.create_entity_resource(
            target_uri,
            target_dataset,
            is_stub=True
        )
        
        # Link stub entity to its type via rdf:type
        self._create_rdf_type_relationship(stub_entity, target_dataset)
        
        # If this is a stub dataset, add metadata from the mapping structure
        if hasattr(context, 'stub_datasets') and target_dataset in context.stub_datasets:
            self._enhance_stub_entity_with_mapping_metadata(stub_entity, target_dataset, relationship, context)
        
        context.entity_cache[target_uri] = stub_entity
        return stub_entity
    
    def _enhance_stub_entity_with_mapping_metadata(self, stub_entity, target_dataset: str, relationship: Dict, context: ProcessingContext):
        """Enhance stub entity with metadata from mapping configuration for legacy data migration."""
        
        # Find the dataset configuration
        target_dataset_config = None
        for dataset_config in context.execution_config.datasets:
            if dataset_config.dataset_name == target_dataset:
                target_dataset_config = dataset_config
                break
        
        if not target_dataset_config:
            return
        
        # Add entity type from mapping
        entity_columns = [col for col in target_dataset_config.columns if col.column_type.value == 'entity']
        if entity_columns:
            primary_entity_column = entity_columns[0]
            
            # Add entity type property
            entity_type_uri = self._generate_property_uri("entity_type")
            self.resource_manager.create_property_triple(
                stub_entity,
                entity_type_uri,
                primary_entity_column.arkumu_type,
                "string"
            )
        
        # Add FK target value as the primary identifier
        target_value = relationship.get('target_value')
        if target_value:
            # Find the target column configuration
            target_column = relationship.get('target_column', 'id')
            for column in target_dataset_config.columns:
                if column.column_name == target_column:
                    identifier_uri = self._generate_property_uri(f"identifier_{column.arkumu_type}")
                    self.resource_manager.create_property_triple(
                        stub_entity,
                        identifier_uri,
                        str(target_value),
                        column.datatype or "string"
                    )
                    break
        
        # Add metadata indicating this is a stub from legacy migration
        stub_metadata_uri = self._generate_property_uri("legacy_migration_stub")
        self.resource_manager.create_property_triple(
            stub_entity,
            stub_metadata_uri,
            f"true",
            "boolean"
        )
        
        # Add original dataset reference
        original_dataset_uri = self._generate_property_uri("original_dataset")
        self.resource_manager.create_property_triple(
            stub_entity,
            original_dataset_uri,
            target_dataset,
            "string"
        )
        
        logger.debug(f"   🏷️  Enhanced stub entity {target_uri} with mapping metadata from '{target_dataset}'")
    
    def _get_target_dataset_from_fk(self, fk_column: str, context: ProcessingContext) -> str:
        """Get target dataset for FK column from configuration"""
        for fk_rel in context.execution_config.fk_relationships:
            if fk_rel.source_column == fk_column:
                return fk_rel.target_dataset
        
        return f"unknown_target_for_{fk_column}"
    
    def _check_orphaned_fk_references(self, skipped_dataset: str, context: ProcessingContext):
        """Check for FK references pointing to skipped datasets and create stub entities to preserve integrity."""
        orphaned_refs = []
        
        # Check all FK relationships that point to this skipped dataset
        for fk_rel in context.execution_config.fk_relationships:
            if fk_rel.target_dataset == skipped_dataset:
                orphaned_refs.append({
                    'source_dataset': fk_rel.source_dataset,
                    'source_column': fk_rel.source_column,
                    'target_dataset': fk_rel.target_dataset,
                    'target_column': fk_rel.target_column
                })
        
        # Check relationship contexts that reference this dataset
        for rel_context in context.execution_config.relationship_contexts:
            primary_target = self._get_target_dataset_from_fk(rel_context.primary_fk, context)
            secondary_target = self._get_target_dataset_from_fk(rel_context.secondary_fk, context)
            
            if primary_target == skipped_dataset or secondary_target == skipped_dataset:
                orphaned_refs.append({
                    'context_id': rel_context.context_id,
                    'dataset': rel_context.dataset_name,
                    'affected_fk': rel_context.primary_fk if primary_target == skipped_dataset else rel_context.secondary_fk,
                    'target_dataset': skipped_dataset
                })
        
        # Create stub metadata structure for the skipped dataset to preserve FK integrity
        if orphaned_refs:
            logger.info(f"🏗️  PRESERVING FK INTEGRITY: Creating stub structure for skipped dataset '{skipped_dataset}'")
            self._create_stub_dataset_structure(skipped_dataset, orphaned_refs, context)
            
            logger.info(f"   📊 FK references preserved: {len(orphaned_refs)}")
            logger.info(f"   🔧 Stub entities will be created during FK resolution for missing targets")
            
            # Add to statistics as info, not warnings since we're handling it
            self.statistics.add_warning(
                f"Created stub structure for skipped dataset '{skipped_dataset}' to preserve {len(orphaned_refs)} FK references"
            )

    def _create_stub_dataset_structure(self, skipped_dataset: str, orphaned_refs: list, context: ProcessingContext):
        """Create stub dataset structure to preserve FK integrity for legacy data migration."""
        
        # Find the dataset configuration for the skipped dataset
        skipped_dataset_config = None
        for dataset_config in context.execution_config.datasets:
            if dataset_config.dataset_name == skipped_dataset:
                skipped_dataset_config = dataset_config
                break
        
        if not skipped_dataset_config:
            logger.warning(f"Could not find dataset config for '{skipped_dataset}' - cannot create stub structure")
            return
        
        # Create dataset resource for the skipped dataset (metadata container)
        dataset_resource = self.resource_manager.create_dataset_resource(skipped_dataset)
        logger.info(f"   📁 Created dataset resource for '{skipped_dataset}' (metadata container)")
        
        # Extract entity type configuration from the mapping
        entity_columns = [col for col in skipped_dataset_config.columns if col.column_type.value == 'entity']
        if entity_columns:
            primary_entity_column = entity_columns[0]  # Use first entity column as primary
            
            # Create metadata schema entries for the entity type
            entity_type_uri = self._generate_type_uri(skipped_dataset)
            schema_property_uri = self._generate_property_uri("defines_entity_type")
            
            # Create schema triple linking dataset to entity type
            entity_type_resource, _ = Resource.objects.get_or_create(
                uri=entity_type_uri,
                defaults={
                    "resource_type": ResourceType.CLASS,
                    "name": entity_type_uri.split('/')[-1],
                    "is_placeholder": False
                }
            )
            self.resource_manager.create_relationship_triple(
                dataset_resource,
                schema_property_uri,
                entity_type_resource
            )
            logger.info(f"   🏷️  Defined entity type '{primary_entity_column.arkumu_type}' for dataset '{skipped_dataset}'")
        
        # Create property schema definitions from column configurations
        for column in skipped_dataset_config.columns:
            if column.column_type.value in ['regular', 'anchor', 'multi_value']:
                # Create property definition in the metadata schema
                property_uri = self._generate_property_uri(column.arkumu_type)
                property_def_uri = self._generate_property_uri(column.arkumu_type)
                
                # Link dataset to property definition
                schema_property_uri = self._generate_property_uri("defines_property")
                property_def_resource, _ = Resource.objects.get_or_create(
                    uri=property_def_uri,
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": property_def_uri.split('/')[-1],
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                self.resource_manager.create_relationship_triple(
                    dataset_resource,
                    schema_property_uri,
                    property_def_resource
                )
                
                # Add property metadata (type, cardinality, etc.)
                type_uri = self._generate_property_uri("property_datatype")
                self.resource_manager.create_property_triple(
                    property_def_resource,
                    type_uri,
                    column.datatype or "string",
                    "string"
                )
                
                if column.is_multi_value:
                    cardinality_uri = self._generate_property_uri("property_cardinality")
                    self.resource_manager.create_property_triple(
                        property_def_resource,
                        cardinality_uri,
                        "multiple",
                        "string"
                    )
        
        logger.info(f"   📊 Created schema definitions for {len(skipped_dataset_config.columns)} columns")
        
        # Mark this dataset as having stub structure created
        if not hasattr(context, 'stub_datasets'):
            context.stub_datasets = set()
        context.stub_datasets.add(skipped_dataset)

    def _create_mapping_config_from_dataset(self, dataset_config) -> Dict[str, Any]:
        """Create mapping configuration from dataset config."""
        mapping_config = {
            "dataset_name": dataset_config.dataset_name,
            "columns": {},
            "fk_relationships": []
        }
        
        # Convert columns
        for column in dataset_config.columns:
            mapping_config["columns"][column.column_name] = {
                "is_multi_value": column.is_multi_value,
                "multi_value_separator": column.multi_value_separator or ",",
                "column_type": column.column_type.value if hasattr(column.column_type, 'value') else str(column.column_type),
                "is_anchor": column.is_anchor,
                "arkumu_type": column.arkumu_type,
                "datatype": column.datatype,
                "fk_config": getattr(column, 'fk_config', None)
            }
        
        # Include FK relationships
        if hasattr(dataset_config, 'fk_relationships'):
            for fk_rel in dataset_config.fk_relationships:
                mapping_config["fk_relationships"].append({
                    "source_column": fk_rel.source_column,
                    "source_dataset": fk_rel.source_dataset,
                    "target_column": fk_rel.target_column,
                    "target_dataset": fk_rel.target_dataset,
                    "relationship_type": fk_rel.relationship_type
                })
        
        return mapping_config
    
    def _convert_column_configs_to_bulk_format(self, columns: List[ColumnConfig]) -> Dict[str, Dict[str, Any]]:
        """Convert mapping column configs to bulk updater format."""
        column_configs = {}
        
        for column in columns:
            column_configs[column.column_name] = {
                "is_multi_value": column.is_multi_value,
                "multi_value_separator": column.multi_value_separator or ",",
                "column_type": column.column_type.value if hasattr(column.column_type, 'value') else str(column.column_type),
                "is_anchor": column.is_anchor,
                "arkumu_type": column.arkumu_type,
                "datatype": column.datatype
            }
        
        return column_configs
    
    def _log_processing_summary(self, context: ProcessingContext):
        """Log comprehensive processing summary"""
        logger.info(f"\n{'='*60}")
        logger.info("PROCESSING SUMMARY")
        logger.info(f"{'='*60}")
        
        # Dataset summary
        logger.info(f"Datasets processed: {len(context.processed_datasets)}")
        
        # Column type summary across all datasets
        total_regular = 0
        total_anchor = 0
        total_multi_value = 0
        total_fk = 0
        total_ontology = 0
        total_relationship_context = 0
        
        for dataset_config in context.execution_config.datasets:
            if dataset_config.dataset_name in context.processed_datasets:
                column_groups = self._group_columns_by_type(dataset_config.columns)
                total_regular += len(column_groups['regular'])
                total_anchor += len(column_groups['anchor'])
                total_multi_value += len(column_groups['multi_value'])
                total_fk += len(column_groups['foreign_key']) + len(column_groups['multi_value_foreign_key'])
                total_ontology += len(column_groups['external_ontology'])
                total_relationship_context += len(column_groups['relationship_context'])
        
        logger.info(f"\nColumn types across all datasets:")
        logger.info(f"  - Regular columns: {total_regular}")
        logger.info(f"  - Anchor columns: {total_anchor}")
        logger.info(f"  - Multi-value columns: {total_multi_value}")
        logger.info(f"  - Foreign key columns: {total_fk}")
        logger.info(f"  - External ontology columns: {total_ontology}")
        logger.info(f"  - Relationship context columns: {total_relationship_context}")
        
        # FK relationships summary
        logger.info(f"\nFK Relationships:")
        logger.info(f"  - Total defined: {len(context.execution_config.fk_relationships)}")
        logger.info(f"  - Pending resolution: {len(self.pending_relationships)}")
        
        # Relationship contexts summary
        logger.info(f"\nRelationship Contexts (Junction Tables):")
        logger.info(f"  - Total contexts: {len(context.execution_config.relationship_contexts)}")
        
        # Metrics summary
        metrics = self.statistics.current_metrics
        logger.info(f"\nExecution Metrics:")
        logger.info(f"  - Rows processed: {metrics.rows_processed}")
        logger.info(f"  - Resources created: {metrics.resources_created}")
        logger.info(f"  - Triples created: {metrics.triples_created}")
        logger.info(f"  - Relationships created: {metrics.relationships_created}")
        if metrics.errors:
            logger.info(f"  - Errors: {metrics.errors}")
        
        logger.info(f"{'='*60}\n")
    
    def _merge_bulk_stats_to_execution_metrics(self, bulk_stats):
        """Merge BulkUpdateStats into ExecutionMetrics."""
        if not bulk_stats:
            return
        
        metrics = self.statistics.current_metrics
        
        # Map BulkUpdateStats fields to ExecutionMetrics fields
        if hasattr(bulk_stats, 'resources_created'):
            metrics.resources_created += bulk_stats.resources_created
        if hasattr(bulk_stats, 'triples_created'):
            metrics.triples_created += bulk_stats.triples_created
        if hasattr(bulk_stats, 'relationships_created'):
            metrics.relationships_created += bulk_stats.relationships_created
        if hasattr(bulk_stats, 'rows_processed'):
            metrics.rows_processed += bulk_stats.rows_processed
        if hasattr(bulk_stats, 'cells_processed'):
            metrics.cells_processed += bulk_stats.cells_processed
        if hasattr(bulk_stats, 'errors'):
            metrics.errors += bulk_stats.errors
    
    def _generate_mapping_cache_key(self, execution_config: ExecutionConfig) -> str:
        """Generate a stable cache key based on mapping configuration content."""
        # Create a deterministic hash of the mapping configuration
        # This includes datasets, columns, and FK relationships
        # Note: Exclude institution to ensure same cache for same mapping across processors
        config_data = {
            'datasets': [],
            'fk_relationships': []
        }
        
        # Add dataset and column information
        for dataset in execution_config.datasets:
            dataset_data = {
                'name': dataset.dataset_name,
                'columns': []
            }
            for column in dataset.columns:
                column_data = {
                    'name': column.column_name,
                    'type': column.column_type.value if hasattr(column.column_type, 'value') else str(column.column_type),
                    'arkumu_type': column.arkumu_type
                }
                dataset_data['columns'].append(column_data)
            config_data['datasets'].append(dataset_data)
        
        # Add FK relationships
        for fk in execution_config.fk_relationships:
            fk_data = {
                'source_dataset': fk.source_dataset,
                'source_column': fk.source_column,
                'target_dataset': fk.target_dataset,
                'target_column': fk.target_column
            }
            config_data['fk_relationships'].append(fk_data)
        
        # Generate Blake2b hash of the configuration (following resource_manager.py pattern)
        # Use Blake2b with 8-byte digest for better performance than SHA256
        import json
        config_json = json.dumps(config_data, sort_keys=True)
        config_hash = hashlib.blake2b(config_json.encode('utf-8'), digest_size=8).hexdigest()
        
        return config_hash
    
    def _create_complete_schema_blueprints(self, execution_config: ExecutionConfig):
        """Create complete schema blueprints for ALL datasets before CSV processing."""
        # Generate cache key based on mapping_id for stability across imports
        # This ensures all dataset imports from the same mapping share the same blueprints
        mapping_id = execution_config.mapping_id
        blueprint_cache_key = f"schema_blueprints_mapping_{mapping_id}"
        
        # Try to load from cache first
        cached_blueprints = cache.get(blueprint_cache_key)
        
        # Log cache key and result
        logger.info(f"🔍 CACHE: Key mapping_{mapping_id} → {'HIT' if cached_blueprints else 'MISS'}")
        
        if cached_blueprints:
            logger.info(f"🚀 CACHE HIT: Loading existing schema blueprints for mapping {mapping_id}")
            self.dataset_blueprints = cached_blueprints
            
            # Log cache statistics
            total_properties = sum(len(bp.get('property_resources', {})) for bp in self.dataset_blueprints.values())
            total_fk_relationships = sum(len(bp.get('fk_relationships', [])) for bp in self.dataset_blueprints.values())
            logger.info(f"   ✅ Loaded {len(self.dataset_blueprints)} cached schema blueprints")
            logger.info(f"   📊 Total properties: {total_properties}")
            logger.info(f"   🔗 Total FK relationships: {total_fk_relationships}")
            return
        
        # Cache miss - create blueprints from scratch
        logger.info("🏗️  SCHEMA-FIRST: Creating complete schema blueprints for all datasets")
        
        # Phase 1: Create all dataset and entity type resources
        self._create_all_dataset_resources(execution_config.datasets)
        
        # Phase 2: Create property definitions for all columns
        self._create_all_property_definitions(execution_config.datasets)
        
        # Phase 3: Map FK relationships between datasets
        self._map_all_fk_relationships(execution_config.datasets)
        
        # Phase 4: Create schema metadata triples
        self._create_all_schema_metadata_triples()
        
        # Cache the blueprints for future use (1 hour timeout like other caches)
        try:
            cache.set(blueprint_cache_key, self.dataset_blueprints, timeout=3600)
            logger.info(f"💾 CACHE STORED: Schema blueprints cached for mapping {mapping_id} (1h timeout)")
        except Exception as e:
            logger.warning(f"Failed to cache schema blueprints: {e}")
        
        logger.info(f"   ✅ Created {len(self.dataset_blueprints)} complete schema blueprints")
        total_properties = sum(len(bp['property_resources']) for bp in self.dataset_blueprints.values())
        total_fk_relationships = sum(len(bp['fk_relationships']) for bp in self.dataset_blueprints.values())
        logger.info(f"   📊 Total properties: {total_properties}")
        logger.info(f"   🔗 Total FK relationships: {total_fk_relationships}")
    
    def _create_all_dataset_resources(self, datasets):
        """Create dataset and entity type resources for all datasets."""
        logger.info("   📁 Creating dataset and entity type resources...")
        
        for dataset_config in datasets:
            # Create dataset resource (metadata container)
            dataset_resource = self.resource_manager.create_dataset_resource(dataset_config.dataset_name)
            
            # Create entity type resource for this dataset
            entity_type_resource = self._create_entity_type_resource(dataset_config)
            
            # Initialize blueprint
            self.dataset_blueprints[dataset_config.dataset_name] = {
                'dataset_name': dataset_config.dataset_name,
                'dataset_resource': dataset_resource,
                'entity_type_resource': entity_type_resource,
                'property_resources': {},
                'fk_relationships': [],
                'created_at': datetime.now()
            }
            
            logger.info(f"     📁 {dataset_config.dataset_name}: dataset + entity type created")
    
    def _create_entity_type_resource(self, dataset_config):
        """Create entity type resource for a dataset."""
        # Find primary entity column (first entity column)
        entity_columns = [col for col in dataset_config.columns if col.column_type.value == 'entity']
        
        if entity_columns:
            primary_entity_column = entity_columns[0]
            entity_type_name = primary_entity_column.arkumu_type
        else:
            # Fallback: use dataset name as entity type
            entity_type_name = dataset_config.dataset_name
        
        # Create entity type URI
        entity_type_uri = self._generate_type_uri(entity_type_name)
        
        # Generate clean name for display (same logic as URI generation)
        if entity_type_name.startswith('http://') or entity_type_name.startswith('https://'):
            clean_name = entity_type_name
        else:
            # Remove entity-type- prefix if present (same as URI generation)
            clean_name = entity_type_name.replace('entity-type-', '').replace('entity_type_', '')
        
        # Create or get entity type resource
        entity_type_resource, created = Resource.objects.get_or_create(
            uri=entity_type_uri,
            defaults={
                "resource_type": ResourceType.CLASS,
                "name": clean_name,
                "is_placeholder": False,
                "organization": self.organization
            }
        )
        
        return entity_type_resource
    
    def _create_all_property_definitions(self, datasets):
        """Create property definitions for all columns in all datasets."""
        logger.info("   🏷️  Creating property definitions for all columns...")
        
        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            
            for column in dataset_config.columns:
                property_resource = self._create_property_resource(column)
                blueprint['property_resources'][column.column_name] = property_resource
            
            logger.info(f"     🏷️  {dataset_config.dataset_name}: {len(blueprint['property_resources'])} properties created")
    
    def _create_property_resource(self, column):
        """Create property resource for a column."""
        # Generate property URI based on arkumu_type
        property_uri = self._generate_property_uri(column.arkumu_type)
        
        # All columns define properties in the schema (rows will be created later as ResourceType.IRI)
        resource_type = ResourceType.PROPERTY
        
        # Create or get property resource
        property_resource, created = Resource.objects.get_or_create(
            uri=property_uri,
            defaults={
                "resource_type": resource_type,
                "name": column.arkumu_type,
                "is_placeholder": False,
                "organization": self.organization
            }
        )
        
        return property_resource
    
    def _map_all_fk_relationships(self, datasets):
        """Map FK relationships between all datasets."""
        logger.info("   🔗 Mapping FK relationships between datasets...")
        
        total_fk_relationships = 0
        
        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            
            for column in dataset_config.columns:
                # Check if column has FK configuration (not all ColumnConfig implementations may have this)
                if hasattr(column, 'fk_config') and column.fk_config:
                    fk_relationship = self._create_fk_relationship_definition(column, dataset_config.dataset_name)
                    blueprint['fk_relationships'].append(fk_relationship)
                    total_fk_relationships += 1
            
            if blueprint['fk_relationships']:
                logger.info(f"     🔗 {dataset_config.dataset_name}: {len(blueprint['fk_relationships'])} FK relationships mapped")
        
        logger.info(f"   🔗 Total FK relationships mapped: {total_fk_relationships}")
    
    def _create_fk_relationship_definition(self, column, source_dataset):
        """Create FK relationship definition."""
        # fk_config is a dictionary, not an object
        fk_config = column.fk_config
        return {
            'source_dataset': source_dataset,
            'source_column': column.column_name,
            'source_property': column.arkumu_type,
            'target_dataset': fk_config.get('target_dataset', ''),
            'target_column': fk_config.get('target_column', ''),
            'relationship_type': column.arkumu_type,
            'is_multi_value': column.is_multi_value,
            'fk_config': fk_config
        }
    
    def _create_all_schema_metadata_triples(self):
        """Create schema metadata triples linking datasets to entity types and properties."""
        logger.info("   📊 Creating schema metadata triples...")
        
        for blueprint in self.dataset_blueprints.values():
            # Link dataset to entity type
            schema_property_uri = self._generate_property_uri("defines_entity_type")
            self.resource_manager.create_relationship_triple(
                blueprint['dataset_resource'],
                schema_property_uri,
                blueprint['entity_type_resource']
            )
            
            # Link entity type to all properties
            for column_name, property_resource in blueprint['property_resources'].items():
                property_schema_uri = self._generate_property_uri("defines_property")
                self.resource_manager.create_relationship_triple(
                    blueprint['entity_type_resource'],
                    property_schema_uri,
                    property_resource
                )
            
            logger.info(f"     📊 {blueprint['dataset_name']}: schema metadata triples created")
